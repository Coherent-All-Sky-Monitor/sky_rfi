"""
Analysis functions for Sky RFI Monitor.
Handles time-series analysis of object density and field-of-view calculations.
"""

import csv
import json
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from skyfield.api import Star, load, wgs84

from src.config import CONFIG
from src.database import db
from src.utils import log


def calculate_angular_separation(
    az1: float, alt1: float, az2: float, alt2: float
) -> float:
    """
    Calculate angular separation between two sky positions.

    Args:
        az1, alt1: Azimuth and altitude of first position (degrees)
        az2, alt2: Azimuth and altitude of second position (degrees)

    Returns:
        Angular separation in degrees
    """
    # Convert to radians
    az1_rad = math.radians(az1)
    alt1_rad = math.radians(alt1)
    az2_rad = math.radians(az2)
    alt2_rad = math.radians(alt2)

    # Haversine formula for angular separation on a sphere
    delta_alt = alt2_rad - alt1_rad
    delta_az = az2_rad - az1_rad

    a = (
        math.sin(delta_alt / 2) ** 2
        + math.cos(alt1_rad) * math.cos(alt2_rad) * math.sin(delta_az / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))

    return math.degrees(c)


def is_within_fov(
    obj_az: float,
    obj_alt: float,
    center_az: float,
    center_alt: float,
    fov_deg: float,
) -> bool:
    """
    Check if an object is within a circular field of view.

    Args:
        obj_az, obj_alt: Object's azimuth and altitude (degrees)
        center_az, center_alt: FoV center azimuth and altitude (degrees)
        fov_deg: Field of view diameter in degrees

    Returns:
        True if object is within FoV
    """
    separation = calculate_angular_separation(
        obj_az, obj_alt, center_az, center_alt
    )
    return separation <= (fov_deg / 2.0)


def parse_ra_dec(ra_str: str, dec_str: str) -> Tuple[float, float]:
    """
    Parse RA and Dec strings in various formats to decimal degrees.

    Args:
        ra_str: Right Ascension (e.g., "05h34m31.94s" or "83.633083")
        dec_str: Declination (e.g., "+22d00m52.2s" or "22.014500")

    Returns:
        (ra_deg, dec_deg) tuple in decimal degrees
    """
    # Try parsing as sexagesimal first
    if "h" in ra_str or ":" in ra_str:
        # Format: HH:MM:SS or HHhMMmSS.Ss
        ra_str = ra_str.replace("h", ":").replace("m", ":").replace("s", "")
        parts = ra_str.split(":")
        if len(parts) == 3:
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            ra_deg = (h + m / 60 + s / 3600) * 15  # Convert hours to degrees
        else:
            ra_deg = float(ra_str)
    else:
        ra_deg = float(ra_str)

    if "d" in dec_str or ":" in dec_str:
        # Format: DD:MM:SS or DDdMMmSS.Ss
        sign = -1 if dec_str.startswith("-") else 1
        dec_str = (
            dec_str.lstrip("+-")
            .replace("d", ":")
            .replace("m", ":")
            .replace("s", "")
        )
        parts = dec_str.split(":")
        if len(parts) == 3:
            d, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            dec_deg = sign * (d + m / 60 + s / 3600)
        else:
            dec_deg = float(dec_str)
    else:
        dec_deg = float(dec_str)

    return ra_deg, dec_deg


def load_source_catalog() -> Dict[str, Dict[str, Any]]:
    """Load source catalog from JSON file."""
    catalog_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "sources.json"
    )

    try:
        with open(catalog_path, "r") as f:
            data = json.load(f)

        # Create lookup dict by name and aliases
        catalog = {}
        for source in data["sources"]:
            # Add by primary name
            catalog[source["name"].lower()] = source
            # Add by aliases
            for alias in source.get("aliases", []):
                catalog[alias.lower()] = source

        return catalog
    except Exception as e:
        log("ERROR", f"Failed to load source catalog: {e}")
        return {}


def query_source_coordinates(source_name: str) -> Dict[str, Any]:
    """
    Query SIMBAD for source coordinates if not in local catalog.

    Args:
        source_name: Name of astronomical source

    Returns:
        Source info dict with ra, dec, name, type
    """
    try:
        from astroquery.simbad import Simbad

        log("ANALYSIS", f"Querying SIMBAD for '{source_name}'")

        # Query SIMBAD
        result = Simbad.query_object(source_name)

        if result is None:
            log("WARNING", f"Source '{source_name}' not found in SIMBAD")
            return None

        # Extract RA/Dec (in degrees)
        ra_deg = float(result["RA"][0])  # degrees
        dec_deg = float(result["DEC"][0])  # degrees

        # Convert to sexagesimal format for consistency
        ra_hours = ra_deg / 15.0
        ra_h = int(ra_hours)
        ra_m = int((ra_hours - ra_h) * 60)
        ra_s = ((ra_hours - ra_h) * 60 - ra_m) * 60

        dec_sign = "+" if dec_deg >= 0 else "-"
        dec_deg_abs = abs(dec_deg)
        dec_d = int(dec_deg_abs)
        dec_m = int((dec_deg_abs - dec_d) * 60)
        dec_s = ((dec_deg_abs - dec_d) * 60 - dec_m) * 60

        ra_str = f"{ra_h:02d}h{ra_m:02d}m{ra_s:06.3f}s"
        dec_str = f"{dec_sign}{dec_d:02d}d{dec_m:02d}m{dec_s:06.3f}s"

        source_info = {
            "name": source_name,
            "ra": ra_str,
            "dec": dec_str,
            "type": "unknown",
            "source": "SIMBAD",
        }

        log(
            "ANALYSIS",
            f"Found '{source_name}' in SIMBAD: RA={ra_str}, Dec={dec_str}",
        )

        return source_info

    except ImportError:
        log(
            "ERROR",
            "astroquery not installed. Install with: pip install astroquery",
        )
        return None
    except Exception as e:
        log("ERROR", f"Failed to query SIMBAD for '{source_name}': {e}")
        return None


def calculate_meridian_transits(
    source_names: List[str], time_range: Tuple[datetime, datetime]
) -> List[Dict[str, Any]]:
    """
    Calculate meridian transit times for sources within time range.

    Args:
        source_names: List of source names to track
        time_range: (start_time, end_time) tuple

    Returns:
        List of transit events with timestamp, source name, altitude
    """
    catalog = load_source_catalog()
    if not catalog:
        return []

    # Load Skyfield timescale and ephemeris
    ts = load.timescale()
    planets = load("de421.bsp")
    earth = planets["earth"]

    # Create observer location
    observer_location = earth + wgs84.latlon(
        CONFIG.obs_lat, CONFIG.obs_lon, CONFIG.obs_alt
    )

    transits = []
    start_time, end_time = time_range

    # Debug: Check types
    log(
        "ANALYSIS", f"start_time type: {type(start_time)}, value: {start_time}"
    )
    log("ANALYSIS", f"end_time type: {type(end_time)}, value: {end_time}")

    # Ensure we have datetime objects
    if not isinstance(start_time, datetime):
        log("ERROR", f"start_time is {type(start_time)}, expected datetime")
        return []
    if not isinstance(end_time, datetime):
        log("ERROR", f"end_time is {type(end_time)}, expected datetime")
        return []

    for source_name in source_names:
        try:
            # Look up source in catalog
            source_key = source_name.lower()
            source_info = None

            if source_key in catalog:
                source_info = catalog[source_key]
            else:
                # Try querying SIMBAD
                log(
                    "ANALYSIS",
                    f"Source '{source_name}' not in local catalog, "
                    f"querying SIMBAD...",
                )
                source_info = query_source_coordinates(source_name)

                if source_info is None:
                    log(
                        "WARNING",
                        f"Source '{source_name}' not found in catalog "
                        f"or SIMBAD",
                    )
                    continue

            # Parse RA/Dec
            try:
                ra_deg, dec_deg = parse_ra_dec(
                    source_info["ra"], source_info["dec"]
                )
            except Exception as e:
                log(
                    "ERROR",
                    f"Failed to parse coordinates for '{source_name}': {e}",
                )
                continue

            # Create Skyfield Star object
            star = Star(ra_hours=ra_deg / 15, dec_degrees=dec_deg)

            log(
                "ANALYSIS",
                f"Calculating transits for {source_info['name']}: "
                f"RA={ra_deg:.2f}°, Dec={dec_deg:.2f}°",
            )

            # Sample times at 1-minute intervals
            current_time = start_time
            log(
                "ANALYSIS",
                f"Initialized current_time type: {type(current_time)}, "
                f"value: {current_time}",
            )
            prev_az = None
            transit_count = 0

            while current_time <= end_time:
                t = ts.from_datetime(current_time.replace(tzinfo=timezone.utc))

                # Calculate alt/az at observer location
                astrometric = observer_location.at(t).observe(star)
                apparent = astrometric.apparent()
                alt, az, _ = apparent.altaz()

                # Meridian crossing: azimuth transitions through 180°
                # (south) or through 0°/360° (north) for circumpolar
                # sources at high altitudes
                current_az = az.degrees

                if prev_az is not None:
                    # Check for south meridian crossing (most common)
                    if prev_az < 180 and current_az >= 180:
                        transits.append(
                            {
                                "timestamp": current_time,
                                "source": source_info["name"],
                                "altitude": alt.degrees,
                                "azimuth": current_az,
                            }
                        )
                        transit_count += 1
                        log(
                            "ANALYSIS",
                            f"Transit detected at {current_time}: "
                            f"Az={current_az:.1f}°, Alt={alt.degrees:.1f}°",
                        )
                    # Check for north meridian crossing (circumpolar)
                    elif prev_az > 350 and current_az < 10:
                        transits.append(
                            {
                                "timestamp": current_time,
                                "source": source_info["name"],
                                "altitude": alt.degrees,
                                "azimuth": current_az,
                            }
                        )
                        transit_count += 1
                        log(
                            "ANALYSIS",
                            f"Transit detected at {current_time}: "
                            f"Az={current_az:.1f}°, Alt={alt.degrees:.1f}°",
                        )

                prev_az = current_az
                try:
                    current_time = current_time + timedelta(
                        minutes=1
                    )  # Add 1 minute
                except TypeError as e:
                    log(
                        "ERROR",
                        f"TypeError adding timedelta: "
                        f"current_time type={type(current_time)}, "
                        f"value={current_time}",
                    )
                    log("ERROR", f"Error: {e}")
                    raise

            log(
                "ANALYSIS",
                f"Found {transit_count} transits for "
                f"{source_info['name']}",
            )

            # Look for next above-horizon transit after the time range
            # This helps show when sources will be observable even if
            # there was a transit in range
            log(
                "ANALYSIS",
                f"Searching for next above-horizon transit after "
                f"{end_time}",
            )
            search_time = end_time
            max_search_hours = 24  # Search up to 24 hours ahead

            for _ in range(max_search_hours * 60):
                t = ts.from_datetime(search_time.replace(tzinfo=timezone.utc))
                astrometric = observer_location.at(t).observe(star)
                apparent = astrometric.apparent()
                alt, az, _ = apparent.altaz()
                current_az = az.degrees

                if prev_az is not None:
                    if (prev_az < 180 and current_az >= 180) or (
                        prev_az > 350 and current_az < 10
                    ):
                        # Found next transit - check if it's above horizon
                        if alt.degrees > 0:
                            time_until = search_time - end_time
                            hours = int(time_until.total_seconds() // 3600)
                            minutes = int(
                                (time_until.total_seconds() % 3600) // 60
                            )

                            transits.append(
                                {
                                    "timestamp": search_time,
                                    "source": source_info["name"],
                                    "altitude": alt.degrees,
                                    "azimuth": current_az,
                                    "future": True,
                                    "time_until": f"{hours}h {minutes}m",
                                }
                            )
                            log(
                                "ANALYSIS",
                                f"Next observable transit for "
                                f"{source_info['name']}: {search_time} "
                                f"(in {hours}h {minutes}m) at altitude "
                                f"{alt.degrees:.1f}°",
                            )
                            break
                        else:
                            # Transit is below horizon, keep searching
                            log(
                                "ANALYSIS",
                                f"Transit at {search_time} is below "
                                f"horizon (alt={alt.degrees:.1f}°), "
                                f"continuing search...",
                            )

                prev_az = current_az
                search_time = search_time + timedelta(minutes=1)

        except Exception as e:
            log(
                "ERROR",
                f"Error processing source {source_name}: "
                f"{type(e).__name__}: {e}",
            )
            import traceback

            log("ERROR", f"Traceback: {traceback.format_exc()}")
            raise

    return transits


def create_polar_plot(snapshot, center_az, center_alt, fov_deg, object_type):
    """
    Create a polar plot showing FoV overlay on objects from latest snapshot.
    """

    log("ANALYSIS", f"Creating polar plot for snapshot {snapshot['id']}")

    # Get objects from this snapshot
    objects = db.get_snapshot(snapshot["id"])

    # Filter by object type if requested
    if object_type != "all":
        type_filter = "satellite" if object_type == "satellite" else "plane"
        objects = [o for o in objects if o["type"] == type_filter]

    # Separate objects into those in FoV and those not
    objects_in_fov = []
    objects_out_fov = []

    for obj in objects:
        if obj["alt"] > 0:  # Only plot objects above horizon
            if is_within_fov(
                obj["az"], obj["alt"], center_az, center_alt, fov_deg
            ):
                objects_in_fov.append(obj)
            else:
                objects_out_fov.append(obj)

    # Create polar plot
    fig = go.Figure()

    # Plot objects outside FoV
    if objects_out_fov:
        fig.add_trace(
            go.Scatterpolar(
                r=[
                    90 - obj["alt"] for obj in objects_out_fov
                ],  # Convert altitude to radius
                theta=[obj["az"] for obj in objects_out_fov],
                mode="markers",
                name="Objects",
                marker=dict(size=6, color="#999", symbol="circle"),
                hovertemplate=(
                    "%{text}<br>Az: %{theta}°<br>"
                    "Alt: %{customdata}°<extra></extra>"
                ),
                text=[obj["name"] for obj in objects_out_fov],
                customdata=[obj["alt"] for obj in objects_out_fov],
            )
        )

    # Plot objects inside FoV
    if objects_in_fov:
        fig.add_trace(
            go.Scatterpolar(
                r=[90 - obj["alt"] for obj in objects_in_fov],
                theta=[obj["az"] for obj in objects_in_fov],
                mode="markers",
                name="In FoV",
                marker=dict(size=8, color="#2196F3", symbol="circle"),
                hovertemplate=(
                    "%{text}<br>Az: %{theta}°<br>"
                    "Alt: %{customdata}°<extra></extra>"
                ),
                text=[obj["name"] for obj in objects_in_fov],
                customdata=[obj["alt"] for obj in objects_in_fov],
            )
        )

    # Draw FoV as filled circle with 20% opacity
    fov_radius_deg = fov_deg / 2.0

    # For polar plots, generate points around the FoV using spherical geometry
    circle_points = 360
    fov_azimuths = []
    fov_radii = []

    # Special case: if center is at or very near zenith (alt ~90°)
    # The circle is simple - same altitude for all azimuths
    if center_alt >= 89.5:
        log("ANALYSIS", "FoV center near zenith - using simplified circle")
        circle_alt = max(0, center_alt - fov_radius_deg)
        for i in range(circle_points + 1):
            az = (i / circle_points) * 360
            fov_azimuths.append(az)
            fov_radii.append(90 - circle_alt)
    else:
        # Convert center to radians
        center_alt_rad = math.radians(center_alt)
        center_az_rad = math.radians(center_az)
        fov_radius_rad = math.radians(fov_radius_deg)

        # Use spherical geometry to find points on the circle
        for i in range(circle_points + 1):
            # Bearing angle (direction from center)
            bearing = math.radians((i / circle_points) * 360)

            # Using haversine-based destination point formula
            # Given a start point and a bearing and distance,
            # find the destination

            # Convert altitude to zenith angle (from north pole)
            lat1 = center_alt_rad  # In alt/az, alt is like latitude
            lon1 = center_az_rad  # Azimuth is like longitude

            # Destination point at angular distance fov_radius_rad
            lat2 = math.asin(
                math.sin(lat1) * math.cos(fov_radius_rad)
                + math.cos(lat1) * math.sin(fov_radius_rad) * math.cos(bearing)
            )

            dlon = math.atan2(
                math.sin(bearing) * math.sin(fov_radius_rad) * math.cos(lat1),
                math.cos(fov_radius_rad) - math.sin(lat1) * math.sin(lat2),
            )
            lon2 = lon1 + dlon

            # Convert back to degrees
            point_alt = math.degrees(lat2)
            point_az = math.degrees(lon2) % 360

            # Clamp altitude to valid range
            point_alt = max(0, min(90, point_alt))

            fov_azimuths.append(point_az)
            fov_radii.append(90 - point_alt)  # Convert to polar radius

    log(
        "ANALYSIS",
        f"FoV circle has {len(fov_azimuths)} points, "
        f"radius range: {min(fov_radii):.2f}-{max(fov_radii):.2f}",
    )

    # Add filled FoV circle
    fig.add_trace(
        go.Scatterpolar(
            r=fov_radii,
            theta=fov_azimuths,
            mode="lines",
            name="Field of View",
            fill="toself",
            fillcolor="rgba(255, 0, 0, 0.2)",  # Red 20% opacity
            line=dict(color="rgba(255, 0, 0, 0.4)", width=1),
            hoverinfo="skip",
        )
    )

    # Horizon arrays will be loaded from CSV; initialize here
    horizon_azimuths = []
    horizon_altitudes = []

    # Load and plot actual horizon profile from CSV
    horizon_file = os.path.join(
        os.path.dirname(__file__), "..", "data", "horizon_data.csv"
    )
    if os.path.exists(horizon_file):
        horizon_azimuths = []
        horizon_altitudes = []

        with open(horizon_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    az = float(row["azimuth"])
                    alt = float(row["altitude"])
                    horizon_azimuths.append(az)
                    horizon_altitudes.append(
                        90 - alt
                    )  # Convert to polar radius
                except (ValueError, KeyError):
                    continue

        if horizon_azimuths:
            log(
                "ANALYSIS",
                f"Loaded {len(horizon_azimuths)} horizon profile points",
            )

            # Add horizon circle (full 0° horizon) so that the filled terrain
            # area can use "tonext" to fill between terrain and horizon
            horizon_circle_r = [90] * len(horizon_azimuths)
            fig.add_trace(
                go.Scatterpolar(
                    r=horizon_circle_r,
                    theta=horizon_azimuths,
                    mode="lines",
                    name="Horizon (0°)",
                    line=dict(color="black", width=2, dash="dot"),
                    hoverinfo="skip",
                    showlegend=True,
                )
            )

            # Plot actual terrain horizon and fill down to the horizon circle
            fig.add_trace(
                go.Scatterpolar(
                    r=horizon_altitudes,
                    theta=horizon_azimuths,
                    mode="lines",
                    name="Terrain Horizon",
                    line=dict(color="#8B4513", width=2),
                    fill="tonext",
                    fillcolor="rgba(139, 69, 19, 0.3)",
                    hovertemplate=(
                        "Az: %{theta}°<br>"
                        "Alt: %{customdata}°<extra></extra>"
                    ),
                    customdata=[90 - r for r in horizon_altitudes],
                )
            )
        else:
            # No horizon profile; add a default horizon circle at 0° altitude
            theta_full = [i for i in range(0, 361)]
            horizon_circle_r = [90] * len(theta_full)
            fig.add_trace(
                go.Scatterpolar(
                    r=horizon_circle_r,
                    theta=theta_full,
                    mode="lines",
                    name="Horizon (0°)",
                    line=dict(color="black", width=2, dash="dot"),
                    hoverinfo="skip",
                    showlegend=True,
                )
            )
    else:
        log("WARNING", f"Horizon data file not found: {horizon_file}")

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                range=[0, 90],
                tickvals=[0, 30, 60, 90],
                ticktext=["90° (Zenith)", "60°", "30°", "0° (Horizon)"],
                showline=True,
                linewidth=1,
                linecolor="black",
                ticks="outside",
            ),
            angularaxis=dict(
                direction="clockwise",
                rotation=90,
                showline=True,
                linewidth=1,
                linecolor="black",
                ticks="outside",
            ),
            bgcolor="white",
        ),
        showlegend=True,
        title=dict(
            text=(
                f"Sky View - Latest Snapshot "
                f"({snapshot['readable_time']})<br>"
                f"FoV: Az={center_az}°, Alt={center_alt}°, "
                f"Diameter={fov_deg}°"
            ),
            x=0.5,
        ),
        height=700,
        template="plotly_white",
    )

    return fig


def analyze_fov_density(
    center_az: float,
    center_alt: float,
    fov_deg: float,
    object_type: str = "all",
    source_names: List[str] = None,
) -> Dict[str, Any]:
    """
    Analyze object density across all snapshots for a given FoV.

    Args:
        center_az: FoV center azimuth (degrees, 0-360)
        center_alt: FoV center altitude (degrees, 0-90)
        fov_deg: Field of view diameter (degrees)
        object_type: Filter by type: "all", "satellite", "plane"
        source_names:
          Optional list of source names for meridian transit markers

    Returns:
        Dictionary with analysis results and plot data
    """
    log(
        "ANALYSIS",
        f"Analyzing FoV: Az={center_az}°, Alt={center_alt}°, "
        f"FoV={fov_deg}°, Type={object_type}",
    )
    if source_names:
        log(
            "ANALYSIS",
            f"Tracking meridian transits for sources: "
            f"{', '.join(source_names)}",
        )

    # Get all snapshots
    snapshots = db.get_all_snapshots()

    if not snapshots:
        return {
            "error": "No snapshots available",
            "plot_json": None,
            "polar_plot_json": None,
        }

    # First pass: identify top constellations
    constellation_counts = {}
    for snap in snapshots:
        snapshot_id = snap["id"]
        objects = db.get_snapshot(snapshot_id)

        # Filter by object type if requested
        if object_type != "all":
            type_filter = (
                "satellite" if object_type == "satellite" else "plane"
            )
            objects = [o for o in objects if o["type"] == type_filter]

        for obj in objects:
            obj_name = obj["name"].upper()
            # Extract constellation name
            if "STARLINK" in obj_name:
                constellation = "STARLINK"
            elif "ONEWEB" in obj_name:
                constellation = "ONEWEB"
            elif "IRIDIUM" in obj_name:
                constellation = "IRIDIUM"
            elif "COSMOS" in obj_name:
                constellation = "COSMOS"
            elif "ORBCOMM" in obj_name:
                constellation = "ORBCOMM"
            elif "GLOBALSTAR" in obj_name:
                constellation = "GLOBALSTAR"
            elif "SPIRE" in obj_name:
                constellation = "SPIRE"
            elif "PLANET" in obj_name:
                constellation = "PLANET"
            else:
                constellation = "OTHER"

            constellation_counts[constellation] = (
                constellation_counts.get(constellation, 0) + 1
            )

    # Get top 3 constellations
    top_constellations = sorted(
        constellation_counts.items(), key=lambda x: x[1], reverse=True
    )[:3]
    top_names = [name for name, count in top_constellations]

    log("ANALYSIS", f"Top constellations: {top_constellations}")

    # Initialize data arrays
    timestamps = []
    readable_times = []
    objects_in_fov = []
    objects_near_horizon = []  # 0-10 degrees altitude
    objects_above_horizon = []  # Total above 0 degrees

    # Constellation-specific arrays - dynamic based on top 3
    const1_in_fov = []
    const1_near_horizon = []
    const1_above_horizon = []

    const2_in_fov = []
    const2_near_horizon = []
    const2_above_horizon = []

    const3_in_fov = []
    const3_near_horizon = []
    const3_above_horizon = []

    const1_name = top_names[0] if len(top_names) > 0 else "NONE"
    const2_name = top_names[1] if len(top_names) > 1 else "NONE"
    const3_name = top_names[2] if len(top_names) > 2 else "NONE"

    # Process each snapshot
    for snap in snapshots:
        snapshot_id = snap["id"]
        objects = db.get_snapshot(snapshot_id)

        # Filter by object type if requested
        if object_type != "all":
            type_filter = (
                "satellite" if object_type == "satellite" else "plane"
            )
            objects = [o for o in objects if o["type"] == type_filter]

        # Count objects in different categories
        in_fov = 0
        near_horizon = 0
        above_horizon = 0

        # Constellation counts
        c1_fov = c1_hor = c1_above = 0
        c2_fov = c2_hor = c2_above = 0
        c3_fov = c3_hor = c3_above = 0

        for obj in objects:
            obj_az = obj["az"]
            obj_alt = obj["alt"]
            obj_name = obj["name"].upper()

            # Identify constellation
            if "STARLINK" in obj_name:
                constellation = "STARLINK"
            elif "ONEWEB" in obj_name:
                constellation = "ONEWEB"
            elif "IRIDIUM" in obj_name:
                constellation = "IRIDIUM"
            elif "COSMOS" in obj_name:
                constellation = "COSMOS"
            elif "ORBCOMM" in obj_name:
                constellation = "ORBCOMM"
            elif "GLOBALSTAR" in obj_name:
                constellation = "GLOBALSTAR"
            elif "SPIRE" in obj_name:
                constellation = "SPIRE"
            elif "PLANET" in obj_name:
                constellation = "PLANET"
            else:
                constellation = "OTHER"

            is_const1 = constellation == const1_name
            is_const2 = constellation == const2_name
            is_const3 = constellation == const3_name

            # Count all objects above horizon
            if obj_alt > 0:
                above_horizon += 1
                if is_const1:
                    c1_above += 1
                if is_const2:
                    c2_above += 1
                if is_const3:
                    c3_above += 1

                # Count near-horizon objects (0-10 degrees)
                if obj_alt <= 10:
                    near_horizon += 1
                    if is_const1:
                        c1_hor += 1
                    if is_const2:
                        c2_hor += 1
                    if is_const3:
                        c3_hor += 1

                # Count objects in FoV
                if is_within_fov(
                    obj_az, obj_alt, center_az, center_alt, fov_deg
                ):
                    in_fov += 1
                    if is_const1:
                        c1_fov += 1
                    if is_const2:
                        c2_fov += 1
                    if is_const3:
                        c3_fov += 1

        # Store results
        timestamps.append(snap["timestamp"])
        readable_times.append(snap["readable_time"])
        objects_in_fov.append(in_fov)
        objects_near_horizon.append(near_horizon)
        objects_above_horizon.append(above_horizon)

        const1_in_fov.append(c1_fov)
        const1_near_horizon.append(c1_hor)
        const1_above_horizon.append(c1_above)

        const2_in_fov.append(c2_fov)
        const2_near_horizon.append(c2_hor)
        const2_above_horizon.append(c2_above)

        const3_in_fov.append(c3_fov)
        const3_near_horizon.append(c3_hor)
        const3_above_horizon.append(c3_above)

    # Create 3-panel plot
    fig = make_subplots(
        rows=3,
        cols=1,
        subplot_titles=(
            f"Objects in FoV (Az={center_az}°, Alt={center_alt}°, "
            f"FoV={fov_deg}°)",
            "Objects Near Horizon (0-10° altitude)",
            "Total Objects Above Horizon",
        ),
        vertical_spacing=0.08,
        shared_xaxes=True,
    )

    # Convert timestamps to datetime objects for better x-axis formatting
    datetime_objs = [datetime.fromtimestamp(ts) for ts in timestamps]
    log(
        "ANALYSIS",
        f"Created {len(datetime_objs)} datetime objects, "
        f"first type: {type(datetime_objs[0]) if datetime_objs else 'N/A'}",
    )

    # Panel 1: Objects in FoV
    fig.add_trace(
        go.Scatter(
            x=datetime_objs,
            y=objects_in_fov,
            mode="lines+markers",
            name="Total",
            line=dict(color="#2196F3", width=2),
            marker=dict(size=4),
            hovertemplate="%{x}<br>Objects: %{y}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # Add constellation traces to Panel 1
    fig.add_trace(
        go.Scatter(
            x=datetime_objs,
            y=const1_in_fov,
            mode="lines",
            name=const1_name.title(),
            line=dict(color="#FF6B6B", width=1.5, dash="dash"),
            hovertemplate=(
                f"%{{x}}<br>{const1_name.title()}: " f"%{{y}}<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=datetime_objs,
            y=const2_in_fov,
            mode="lines",
            name=const2_name.title(),
            line=dict(color="#4ECDC4", width=1.5, dash="dash"),
            hovertemplate=(
                f"%{{x}}<br>{const2_name.title()}: " f"%{{y}}<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=datetime_objs,
            y=const3_in_fov,
            mode="lines",
            name=const3_name.title(),
            line=dict(color="#95E1D3", width=1.5, dash="dash"),
            hovertemplate=(
                f"%{{x}}<br>{const3_name.title()}: " f"%{{y}}<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )

    # Panel 2: Near-horizon objects
    fig.add_trace(
        go.Scatter(
            x=datetime_objs,
            y=objects_near_horizon,
            mode="lines+markers",
            name="Total",
            line=dict(color="#FF9800", width=2),
            marker=dict(size=4),
            hovertemplate="%{x}<br>Objects: %{y}<extra></extra>",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=datetime_objs,
            y=const1_near_horizon,
            mode="lines",
            name=const1_name.title(),
            line=dict(color="#FF6B6B", width=1.5, dash="dash"),
            hovertemplate=(
                f"%{{x}}<br>{const1_name.title()}: " f"%{{y}}<extra></extra>"
            ),
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=datetime_objs,
            y=const2_near_horizon,
            mode="lines",
            name=const2_name.title(),
            line=dict(color="#4ECDC4", width=1.5, dash="dash"),
            hovertemplate=(
                f"%{{x}}<br>{const2_name.title()}: " f"%{{y}}<extra></extra>"
            ),
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=datetime_objs,
            y=const3_near_horizon,
            mode="lines",
            name=const3_name.title(),
            line=dict(color="#95E1D3", width=1.5, dash="dash"),
            hovertemplate=(
                f"%{{x}}<br>{const3_name.title()}: " f"%{{y}}<extra></extra>"
            ),
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # Panel 3: Total above horizon
    fig.add_trace(
        go.Scatter(
            x=datetime_objs,
            y=objects_above_horizon,
            mode="lines+markers",
            name="Total",
            line=dict(color="#4CAF50", width=2),
            marker=dict(size=4),
            hovertemplate="%{x}<br>Objects: %{y}<extra></extra>",
            showlegend=False,
        ),
        row=3,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=datetime_objs,
            y=const1_above_horizon,
            mode="lines",
            name=const1_name.title(),
            line=dict(color="#FF6B6B", width=1.5, dash="dash"),
            hovertemplate=(
                f"%{{x}}<br>{const1_name.title()}: " f"%{{y}}<extra></extra>"
            ),
            showlegend=False,
        ),
        row=3,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=datetime_objs,
            y=const2_above_horizon,
            mode="lines",
            name=const2_name.title(),
            line=dict(color="#4ECDC4", width=1.5, dash="dash"),
            hovertemplate=(
                f"%{{x}}<br>{const2_name.title()}: " f"%{{y}}<extra></extra>"
            ),
            showlegend=False,
        ),
        row=3,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=datetime_objs,
            y=const3_above_horizon,
            mode="lines",
            name=const3_name.title(),
            line=dict(color="#95E1D3", width=1.5, dash="dash"),
            hovertemplate=(
                f"%{{x}}<br>{const3_name.title()}: " f"%{{y}}<extra></extra>"
            ),
            showlegend=False,
        ),
        row=3,
        col=1,
    )

    # Update layout with axes on all sides and major/minor ticks
    for row in [1, 2, 3]:
        fig.update_xaxes(
            title_text="Time" if row == 3 else None,
            row=row,
            col=1,
            mirror="all",
            ticks="inside",
            showline=True,
            linewidth=1,
            linecolor="black",
            minor=dict(
                ticks="inside",
                ticklen=3,
                tickcolor="black",
                showgrid=True,
            ),
        )
        fig.update_yaxes(
            title_text="Count",
            row=row,
            col=1,
            mirror="all",
            ticks="inside",
            showline=True,
            linewidth=1,
            linecolor="black",
            minor=dict(
                ticks="inside",
                ticklen=3,
                tickcolor="black",
                showgrid=True,
            ),
        )

    # Add meridian transit markers if sources specified
    transit_info = []
    future_transits = []
    if source_names:
        # Calculate transits within time range
        # Ensure we have datetime objects, not timestamps
        start_dt = (
            datetime_objs[0]
            if isinstance(datetime_objs[0], datetime)
            else datetime.fromtimestamp(datetime_objs[0])
        )
        end_dt = (
            datetime_objs[-1]
            if isinstance(datetime_objs[-1], datetime)
            else datetime.fromtimestamp(datetime_objs[-1])
        )
        time_range = (start_dt, end_dt)
        log(
            "ANALYSIS",
            f"Transit time range: {start_dt} to {end_dt}",
        )
        transits = calculate_meridian_transits(source_names, time_range)

        # Separate current and future transits
        log("ANALYSIS", f"Processing {len(transits)} transits")
        for i, transit in enumerate(transits):
            log("ANALYSIS", f"Processing transit {i + 1}: {transit}")
            transit_time = transit["timestamp"]
            log(
                "ANALYSIS",
                f"transit_time type: {type(transit_time)}, "
                f"value: {transit_time}",
            )
            source = transit["source"]
            altitude = transit["altitude"]
            is_future = transit.get("future", False)

            if is_future:
                # Store future transit info
                log("ANALYSIS", f"Processing future transit for {source}")
                future_transits.append(
                    {
                        "source": source,
                        "time": transit_time.isoformat(),
                        "altitude": round(altitude, 2),
                        "time_until": transit.get("time_until", "N/A"),
                    }
                )
            else:
                # Add vertical line to all three panels for transits in range
                log("ANALYSIS", f"Adding vline for {source} at {transit_time}")
                for row in [1, 2, 3]:
                    fig.add_vline(
                        x=transit_time,
                        line_width=2,
                        line_dash="dot",
                        line_color="purple",
                        opacity=0.6,
                        row=row,
                        col=1,
                    )

                # Add invisible trace for legend entry (only once)
                if len(transit_info) == 0:  # First transit only
                    fig.add_trace(
                        go.Scatter(
                            x=[None],
                            y=[None],
                            mode="lines",
                            name=f"{source} Transit",
                            line=dict(color="purple", width=2, dash="dot"),
                            showlegend=True,
                        ),
                        row=1,
                        col=1,
                    )

                transit_info.append(
                    {
                        "source": source,
                        "time": transit_time.isoformat(),
                        "altitude": round(altitude, 2),
                    }
                )

        log(
            "ANALYSIS",
            f"Added {len(transit_info)} meridian transit markers in range",
        )
        if future_transits:
            next_list = [
                f"{t['source']} in {t['time_until']}" for t in future_transits
            ]
            log(
                "ANALYSIS",
                "Next transits: " + ", ".join(next_list),
            )
            log(
                "ANALYSIS",
                f"Future transits data: {future_transits}",
            )

    log("ANALYSIS", f"Returning future_transits: {future_transits}")
    fig.update_layout(
        height=900,
        showlegend=True,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
        ),
        title_text=f"Sky Object Density Analysis ({object_type.title()})",
        title_x=0.5,
        hovermode="x unified",
        template="plotly_white",
    )

    # Convert to JSON for client-side rendering
    plot_json = fig.to_json()

    # Create polar plot for latest snapshot
    polar_plot_json = None
    try:
        log("ANALYSIS", "Creating polar plot from latest snapshot")
        polar_fig = create_polar_plot(
            snapshots[-1], center_az, center_alt, fov_deg, object_type
        )
        polar_plot_json = polar_fig.to_json()
        log("ANALYSIS", "Polar plot created successfully")
    except Exception as e:
        log("ERROR", f"Failed to create polar plot: {e}")
        import traceback

        log("ERROR", traceback.format_exc())

    # Calculate statistics
    stats = {
        "snapshots_analyzed": len(snapshots),
        "time_range": {
            "start": readable_times[0] if readable_times else None,
            "end": readable_times[-1] if readable_times else None,
        },
        "fov_stats": {
            "mean": float(np.mean(objects_in_fov)) if objects_in_fov else 0,
            "max": int(np.max(objects_in_fov)) if objects_in_fov else 0,
            "min": int(np.min(objects_in_fov)) if objects_in_fov else 0,
            "std": float(np.std(objects_in_fov)) if objects_in_fov else 0,
        },
        "horizon_stats": {
            "mean": (
                float(np.mean(objects_near_horizon))
                if objects_near_horizon
                else 0
            ),
            "max": (
                int(np.max(objects_near_horizon))
                if objects_near_horizon
                else 0
            ),
            "min": (
                int(np.min(objects_near_horizon))
                if objects_near_horizon
                else 0
            ),
        },
        "total_stats": {
            "mean": (
                float(np.mean(objects_above_horizon))
                if objects_above_horizon
                else 0
            ),
            "max": (
                int(np.max(objects_above_horizon))
                if objects_above_horizon
                else 0
            ),
            "min": (
                int(np.min(objects_above_horizon))
                if objects_above_horizon
                else 0
            ),
        },
    }

    # Add future transit information to stats if available
    if future_transits:
        stats["next_transits"] = future_transits

    log(
        "ANALYSIS",
        f"Analysis complete: {stats['snapshots_analyzed']} "
        "snapshots processed",
    )

    return {
        "plot_json": plot_json,
        "polar_plot_json": polar_plot_json,
        "stats": stats,
        "parameters": {
            "center_az": center_az,
            "center_alt": center_alt,
            "fov_deg": fov_deg,
            "object_type": object_type,
        },
        "transits": transit_info,
        "future_transits": future_transits,
    }
