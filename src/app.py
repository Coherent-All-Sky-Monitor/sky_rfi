"""
Sky RFI Monitor
"""

import fcntl
import hashlib
import json
import math
import os
import secrets
import threading

import numpy as np
import plotly.graph_objects as go  # type: ignore
from flask import Flask, abort, jsonify, render_template, request

from src.api_clients import aircraft_client, horizon_client
from src.calculations import position_calc
from src.config import CONFIG
from src.database import db
from src.scheduler import scheduler, state
from src.utils import format_timestamp, log

# Initialize Flask app with paths relative to project root
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(
    __name__,
    template_folder=os.path.join(_project_root, "templates"),
    static_folder=os.path.join(_project_root, "static"),
)

# Generate or load API token (shared across workers via file)
API_TOKEN_FILE = os.path.join(_project_root, "data", ".api_token")
os.makedirs(os.path.dirname(API_TOKEN_FILE), exist_ok=True)

# Use file-based locking to ensure single token generation

lock_file = os.path.join(_project_root, "data", ".api_token.lock")
with open(lock_file, "w", encoding="utf-8") as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    try:
        if os.path.exists(API_TOKEN_FILE):
            with open(API_TOKEN_FILE, "r", encoding="utf-8") as f:
                API_TOKEN = f.read().strip()
        else:
            API_TOKEN = secrets.token_urlsafe(32)
            with open(API_TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(API_TOKEN)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

log("SYSTEM", f"API token: {API_TOKEN[:8]}... (PID {os.getpid()})")

# Start background scheduler thread (only one process should run it)
# Use atomic file locking to ensure only one worker starts the scheduler
scheduler_lock_file = os.path.join(_project_root, "data", ".scheduler_running")
scheduler_lock_fd = os.path.join(_project_root, "data", ".scheduler.lock")

with open(scheduler_lock_fd, "w", encoding="utf-8") as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    try:
        should_run_scheduler = False

        if os.path.exists(scheduler_lock_file):
            # Check if the PID in the lock file is still running
            try:
                with open(scheduler_lock_file, "r", encoding="utf-8") as f:
                    old_pid = int(f.read().strip())

                # Check if process is alive (send signal 0)
                try:
                    os.kill(old_pid, 0)
                    # Process is alive, don't start scheduler
                    log(
                        "SYSTEM", f"Scheduler already running in PID {old_pid}"
                    )
                except (OSError, ProcessLookupError):
                    # Process is dead, remove stale lock
                    STALE_LOCK_MSG = (
                        "Removing stale scheduler lock (PID "
                        f"{old_pid} is dead)"
                    )
                    log("SYSTEM", STALE_LOCK_MSG)
                    os.remove(scheduler_lock_file)
                    should_run_scheduler = True
            except (ValueError, FileNotFoundError):
                # Invalid lock file, remove it
                log("SYSTEM", "Removing invalid scheduler lock file")
                try:
                    os.remove(scheduler_lock_file)
                except FileNotFoundError:
                    pass
                should_run_scheduler = True
        else:
            should_run_scheduler = True

        if should_run_scheduler:
            with open(scheduler_lock_file, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            scheduler_thread = threading.Thread(target=scheduler.run_forever)
            scheduler_thread.daemon = True
            scheduler_thread.start()
            log("SYSTEM", "Background scheduler started (master worker)")
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def format_traces(objects):
    """
    Format objects into plot traces for visualization.

    Args:
        objects: List of object dictionaries

    Returns:
        Dictionary with traces_2d, traces_3d, stats, and top constellations
    """
    grouped = {}
    stats = {
        "sat_count": 0,
        "plane_count": 0,
        "planes_blocked": 0,
        "constellations": {},
    }

    # Group objects
    for o in objects:
        gid = o["group"]
        grouped.setdefault(gid, []).append(o)
        if o["type"] == "plane":
            stats["plane_count"] += 1
        else:
            stats["sat_count"] += 1
            const_count = stats["constellations"].get(gid, 0)
            stats["constellations"][gid] = const_count + 1

    # Get top 5 constellations
    top_5_sorted = sorted(
        stats["constellations"].items(),
        key=lambda x: x[1],
        reverse=True,
    )
    top_5 = top_5_sorted[:5]

    traces_2d = []
    traces_3d = []

    # Sort groups (prioritize Aircraft, then priority
    # constellations, then by count)
    def sort_key(g):
        if g == "Aircraft":
            return 1000
        if g in CONFIG.priority_constellations:
            return 500
        return len(grouped[g])

    sorted_groups = sorted(grouped.keys(), key=sort_key, reverse=True)

    # Create traces for each group
    r_earth = 6371

    for group in sorted_groups:
        sub = grouped[group]

        # Default styling
        defaults = CONFIG.default_satellite_style
        hash_val = int(hashlib.sha256(group.encode()).hexdigest(), 16)
        color = f"hsl({hash_val % 360}, 70%, 50%)"
        symbol = defaults.get("symbol", "circle")
        size = defaults.get("size", 3)
        opacity = defaults.get("opacity", 0.7)

        # Apply priority constellation styling
        if group in CONFIG.priority_constellations:
            conf = CONFIG.priority_constellations[group]
            color = conf.get("color", color)
            symbol = conf.get("symbol", symbol)
            size = conf.get("size", size)
            opacity = conf.get("opacity", opacity)

        # 2D trace
        traces_2d.append(
            {
                "name": group,
                "mode": "markers",
                "type": "scatter",
                "x": [o["az"] for o in sub],
                "y": [o["alt"] for o in sub],
                "text": [o["name"] for o in sub],
                "marker": {
                    "symbol": symbol,
                    "color": color,
                    "size": size,
                    "opacity": opacity,
                },
            }
        )

        # 3D trace with altitude scaling
        x3, y3, z3 = [], [], []
        for o in sub:
            ox, oy, oz = o["x"] or 0, o["y"] or 0, o["z"] or 0
            r_real = math.sqrt(ox**2 + oy**2 + oz**2)
            if r_real < 100:
                r_real = r_earth
            alt_real = max(0, r_real - r_earth)
            alt_vis = (alt_real**CONFIG.globe_scale_power) * 85
            scale = (r_earth + alt_vis) / r_real
            x3.append(ox * scale)
            y3.append(oy * scale)
            z3.append(oz * scale)  # noqa: E501

        traces_3d.append(
            {
                "name": group,
                "type": "scatter3d",
                "mode": "markers",
                "x": x3,
                "y": y3,
                "z": z3,
                "text": [o["name"] for o in sub],
                "marker": {
                    "symbol": "circle",
                    "color": color,
                    "size": 3,
                    "opacity": 0.9,
                },
            }
        )

    return {
        "traces_2d": traces_2d,
        "traces_3d": traces_3d,
        "stats": stats,
        "top": top_5,
    }


def format_public_output(objects, timestamp_str):
    """Format objects for public API output."""
    data = {"airplanes": {}, "satellites": {}}

    # Process objects
    for o in objects:
        alt = round(o["alt"], 2)  # Degrees
        az = round(o["az"], 2)  # Degrees
        # Distance is in meters
        dist = round(o["dist"], 2) if "dist" in o else None

        if o["type"] == "plane":
            callsign = o["name"]
            plane_data = {"alt": alt, "az": az, "distance": dist}
            data["airplanes"][callsign] = plane_data
        else:
            const_name = o["group"]
            sat_name = o["name"]

            if const_name not in data["satellites"]:
                data["satellites"][const_name] = {
                    "constellation_name": const_name,
                    "list": {},
                }

            sat_data = {"alt": alt, "az": az}
            data["satellites"][const_name]["list"][sat_name] = sat_data

    return {timestamp_str: data}


# ---------------------------------------------------------
# API ENDPOINTS (Protected)
# ---------------------------------------------------------


@app.route("/api/public/latest")
def public_api_latest():
    """Get latest position data (Public)."""
    import time

    # Wait for aircraft API cooldown if needed
    cooldown = aircraft_client.cooldown_until
    if time.time() < cooldown:
        wait_seconds = int(cooldown - time.time())
        log(
            "API",
            f"Public API waiting {wait_seconds}s for aircraft cooldown...",
        )
        time.sleep(wait_seconds + 1)  # Add 1 second buffer

    # Fetch fresh aircraft data
    aircraft = aircraft_client.fetch_aircraft()
    state.set_aircraft(aircraft)
    state.set_aircraft_rate_limit(aircraft_client.cooldown_until)

    # Use cached TLE data
    tles = state.get_tles()
    objects = position_calc.calculate_visible_objects(tles, aircraft)

    return jsonify(format_public_output(objects, format_timestamp()))


@app.route("/api/public/snapshots")
def public_api_list_snapshots():
    """Get list of snapshot IDs and timestamps (Public)."""
    snapshots = db.get_all_snapshots()
    result = [
        {"id": s["id"], "timestamp": s["readable_time"]} for s in snapshots
    ]
    return jsonify(result)


@app.route("/api/public/snapshot/<int:snapshot_id>")
def public_api_get_snapshot(snapshot_id):
    """Get specific snapshot data (Public)."""
    objects = db.get_snapshot(snapshot_id)

    # Get timestamp from snapshots list
    all_snaps = db.get_all_snapshots()
    timestamp_str = "unknown"
    for s in all_snaps:
        if s["id"] == snapshot_id:
            timestamp_str = s["readable_time"]
            break

    response = format_public_output(objects, timestamp_str)
    response[timestamp_str]["snapshot_id"] = snapshot_id

    return jsonify(response)


def verify_api_token():
    """Verify API token from request header."""
    token = request.headers.get("X-API-Token")
    if token != API_TOKEN:
        unauth_msg = (
            f"Unauthorized API access attempt from {request.remote_addr}"
        )
        log("API", unauth_msg)
        abort(403)


@app.route("/api/snapshot/<int:snapshot_id>")
def api_snapshot(snapshot_id):
    """Get specific historical snapshot."""
    verify_api_token()
    objects = db.get_snapshot(snapshot_id)

    # Count objects by type
    sat_count = sum(1 for o in objects if o["type"] == "satellite")
    plane_count = sum(1 for o in objects if o["type"] == "plane")

    # Get snapshot timestamp
    all_snaps = db.get_all_snapshots()
    timestamp_str = "unknown"
    for s in all_snaps:
        if s["id"] == snapshot_id:
            timestamp_str = s["readable_time"]
            break

    log(
        "VIEW",
        f"Displaying snapshot #{snapshot_id} from {timestamp_str}: "
        f"{sat_count} satellites, {plane_count} aircraft",
    )

    response = format_traces(objects)
    # Add current rate limit status so banner shows even when
    # viewing old snapshots
    response["aircraft_rate_limit_until"] = state.get_aircraft_rate_limit()

    return jsonify(response)


@app.route("/api/status")
def api_status():
    """Get current system status."""
    verify_api_token()
    scheduler_status = scheduler.get_status()
    scheduler_status["aircraft_rate_limit_until"] = (
        state.get_aircraft_rate_limit()
    )
    return jsonify(scheduler_status)


@app.route("/api/history")
def api_history():
    """Get list of all snapshots."""
    verify_api_token()
    return jsonify(db.get_all_snapshots())


@app.route("/api/force_snapshot", methods=["POST"])
def api_force_snapshot():
    """Force a snapshot to be taken immediately."""
    verify_api_token()

    # Get wait_for_aircraft parameter (default True)
    if request.is_json:
        wait_for_aircraft = request.json.get("wait_for_aircraft", True)
    else:
        wait_for_aircraft = True

    result = scheduler.force_snapshot(wait_for_aircraft=wait_for_aircraft)

    if result["status"] == "success":
        status_code = 200
    elif result["status"] == "rate_limited":
        status_code = 429
    else:
        status_code = 400
    return jsonify(result), status_code


@app.route("/api/geo")
def api_geo():
    """Get cached geospatial data."""
    verify_api_token()
    if os.path.exists(CONFIG.geo_cache_file):
        with open(CONFIG.geo_cache_file, "r", encoding="utf-8") as geo_file:
            return jsonify(json.load(geo_file))
    return jsonify(None)


# ---------------------------------------------------------
# MAIN PAGE
# ---------------------------------------------------------


@app.route("/")
def index():
    """Render main page with initial plot configurations."""
    h_az, h_alt, _ = horizon_client.get_horizon()
    if not h_az:
        h_az, h_alt = [0, 360], [0, 0]

    # Legend configuration
    legend_cfg = {
        "orientation": "h",
        "yanchor": "top",
        "y": -0.2,
        "xanchor": "center",
        "x": 0.5,
        "font": {"color": "white"},
        "itemwidth": 70,
    }

    # Check if 'autosize' is preferred or specific height
    common_layout = {
        "template": "plotly_dark",
        "autosize": True,
        "margin": {"t": 40, "b": 120, "l": 40, "r": 40},
        "legend": legend_cfg,
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
    }

    # RECTANGULAR VIEW
    fig_rect = go.Figure()

    # Add beam width indicator
    beam_edge = 90 - (CONFIG.beam_width_deg / 2)
    fig_rect.add_hrect(
        y0=beam_edge,
        y1=90,
        fillcolor="lime",
        opacity=0.15,
        line_width=0,
        layer="below",
    )

    # Add terrain (dark and light versions)
    fig_rect.add_trace(
        go.Scatter(
            x=h_az,
            y=h_alt,
            mode="lines",
            line={"color": "#888", "width": 1},
            fill="tozeroy",
            fillcolor="rgba(128,128,128,0.3)",
            name="Terrain",
            hoverinfo="skip",
        )
    )
    fig_rect.add_trace(
        go.Scatter(
            x=h_az,
            y=h_alt,
            mode="lines",
            line={"color": "#ccc", "width": 1},
            fill="tozeroy",
            fillcolor="rgba(200,200,200,0.25)",
            name="Terrain",
            visible=False,
            hoverinfo="skip",
        )
    )

    layout_rect = common_layout.copy()
    layout_rect.update(
        {
            "title": "Rectangular View",
            "xaxis": {
                "range": [0, 360],
                "dtick": 45,
                "title": "Azimuth",
                "showgrid": True,
                "gridcolor": "#444",
                "showline": True,
                "mirror": True,
            },
            "yaxis": {
                "range": [0, 90],
                "title": "Altitude",
                "showgrid": True,
                "gridcolor": "#444",
                "showline": True,
                "mirror": True,
            },
        }
    )
    fig_rect.update_layout(**layout_rect)

    # POLAR VIEW
    fig_polar = go.Figure()

    # Add beam width indicator
    theta_c = np.linspace(0, 360, 100)
    r_c = [beam_edge] * 100
    fig_polar.add_trace(
        go.Scatterpolar(
            r=r_c,
            theta=theta_c,
            mode="lines",
            fill="toself",
            fillcolor="rgba(0,255,0,0.15)",
            line_width=0,
            name="Beam",
            hoverinfo="skip",
        )
    )

    # Add terrain (dark and light versions)
    # Convert altitudes to radial distances: r = 90 - altitude
    poly_az = list(h_az) + list(reversed(h_az[:-1]))
    poly_alt_r = [90 - alt for alt in h_alt]
    poly_fill_r = poly_alt_r + [90] * (len(poly_alt_r) - 1)

    fig_polar.add_trace(
        go.Scatterpolar(
            r=poly_fill_r,
            theta=poly_az,
            mode="lines",
            fill="toself",
            fillcolor="rgba(128,128,128,0.3)",
            line={"color": "#888"},
            name="Terrain",
            hoverinfo="skip",
        )
    )
    fig_polar.add_trace(
        go.Scatterpolar(
            r=poly_fill_r,
            theta=poly_az,
            mode="lines",
            fill="toself",
            fillcolor="rgba(200,200,200,0.25)",
            line={"color": "#ccc"},
            name="Terrain",
            visible=False,
            hoverinfo="skip",
        )
    )

    layout_polar = common_layout.copy()
    layout_polar.update(
        {
            "title": "Polar View",
            "height": 1000,
            "polar": {
                "radialaxis": {
                    "range": [0, 90],
                    "showgrid": True,
                    "gridcolor": "#444",
                },
                "angularaxis": {
                    "rotation": 90,
                    "direction": "clockwise",
                    "showgrid": True,
                    "gridcolor": "#444",
                },
                "bgcolor": "rgba(0,0,0,0)",
            },
        }
    )
    fig_polar.update_layout(**layout_polar)

    # 3D GLOBE
    fig_globe = go.Figure()

    layout_globe = {
        "template": "plotly_dark",
        "autosize": True,
        "height": 900,  # Ensure initial height is large
        "margin": {"t": 0, "b": 0, "l": 0, "r": 0},
        "showlegend": False,
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "title": {
            "text": "3D View",
            "y": 0.95,
            "x": 0.5,
            "xanchor": "center",
            "yanchor": "top",
        },
        "scene": {
            "xaxis": {
                "visible": False,
                "showgrid": False,
                "zeroline": False,
                "showticklabels": False,
            },
            "yaxis": {
                "visible": False,
                "showgrid": False,
                "zeroline": False,
                "showticklabels": False,
            },
            "zaxis": {
                "visible": False,
                "showgrid": False,
                "zeroline": False,
                "showticklabels": False,
            },
            "aspectmode": "data",
            "dragmode": "orbit",
            "bgcolor": "rgba(0,0,0,0)",
        },
    }
    fig_globe.update_layout(**layout_globe)

    # Render template with plots and config
    return render_template(
        "index.html",
        api_token=API_TOKEN,
        obs_name=CONFIG.obs_name,
        obs_lat=CONFIG.obs_lat,
        obs_lon=CONFIG.obs_lon,
        obs_alt=CONFIG.obs_alt,
        live_poll_interval_ms=CONFIG.live_poll_interval_ms,
        live_poll_sec=CONFIG.live_poll_interval_ms / 1000,
        live_view_url=CONFIG.live_view_url,
        fig_rect_json=fig_rect.to_json(),
        fig_polar_json=fig_polar.to_json(),
        fig_globe_json=fig_globe.to_json(),
    )


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

if __name__ == "__main__":
    # Get server config
    host = CONFIG.dev_host
    port = CONFIG.dev_port

    log("SYSTEM", f"Server running: http://{host}:{port}")

    # Run Flask app
    app.run(host=host, port=port, debug=True, use_reloader=False)
