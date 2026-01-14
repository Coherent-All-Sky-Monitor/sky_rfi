import time
import sqlite3
import threading
import datetime
import io
import os
import requests
import zipfile
import re
import csv
import numpy as np
import hashlib
import json
import math
from flask import Flask, jsonify, request
import plotly.graph_objects as go
from skyfield.api import load, wgs84
from skyfield.sgp4lib import EarthSatellite

# --- CONFIGURATION ---
DB_NAME = "casm_rfi_sky.db"
HORIZON_FILE = "horizon_data.csv"
FETCH_INTERVAL_MINUTES = 30
RETENTION_DAYS = 7  
OVRO_LAT = 37.2317
OVRO_LON = -118.2951
OVRO_ALT = 1222
PANORAMA_ID = "BTV9VXUH"
BEAM_WIDTH_DEG = 100

# --- RATE LIMIT CONFIG ---
MIN_API_INTERVAL = 300   # 5 Minute Window
MAX_BURST_UPDATES = 5    # Allow 5 updates within that window

PRIORITY_CONSTELLATIONS = {
    'MUOS':     {'color': 'magenta', 'symbol': 'square', 'size': 12, 'opacity': 1.0},
    'STARLINK': {'color': 'grey',    'symbol': 'star',   'size': 8,  'opacity': 0.5},
}

app = Flask(__name__)

# GLOBAL STATE FOR RATE LIMITING
LAST_FETCH_TIME = 0
BURST_COUNT = 0

# ---------------------------------------------------------
# 1. DATABASE & INITIALIZATION
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON")
    c.execute('''CREATE TABLE IF NOT EXISTS snapshots
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL, readable_time TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS objects
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  snapshot_id INTEGER, 
                  name TEXT, 
                  type TEXT, 
                  group_id TEXT,
                  az_deg REAL, 
                  alt_deg REAL, 
                  dist_m REAL,
                  FOREIGN KEY(snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE)''')
    conn.commit()
    conn.close()

def init_horizon():
    if os.path.exists(HORIZON_FILE): return
    print("Downloading Horizon...")
    try:
        url = f"https://www.heywhatsthat.com/api/horizon.csv?id={PANORAMA_ID}&resolution=.1"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        with open(HORIZON_FILE, 'wb') as f: f.write(r.content)
    except Exception as e: print(f"Horizon fetch failed: {e}")

def get_horizon_offline():
    if not os.path.exists(HORIZON_FILE): return [], [], []
    az_list, alt_list, dist_list = [], [], []
    try:
        with open(HORIZON_FILE, 'r') as f:
            reader = csv.reader(f)
            next(reader, None)
            raw = []
            for row in reader:
                if len(row) >= 4: raw.append((float(row[1]), float(row[2]), float(row[3])))
            raw.sort(key=lambda x: x[0])
            for r in raw: az_list.append(r[0]); alt_list.append(r[1]); dist_list.append(r[2])
        return az_list, alt_list, dist_list
    except: return [], [], []

def get_latest_snapshot_time():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT readable_time FROM snapshots ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else "No Data"

# ---------------------------------------------------------
# 2. DATA FETCHING & CLEANUP
# ---------------------------------------------------------
def cleanup_old_data():
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("PRAGMA foreign_keys = ON")
        cutoff = time.time() - (RETENTION_DAYS * 86400)
        c.execute("DELETE FROM snapshots WHERE timestamp < ?", (cutoff,))
        conn.commit(); conn.close()
    except Exception as e: print(f"Cleanup failed: {e}")

def fetch_job():
    global LAST_FETCH_TIME, BURST_COUNT
    
    now = time.time()
    time_since_last = now - LAST_FETCH_TIME
    
    # Reset Burst Counter if window has passed
    if time_since_last >= MIN_API_INTERVAL:
        BURST_COUNT = 0
    
    # Check Limit
    if BURST_COUNT >= MAX_BURST_UPDATES:
        remaining = int(MIN_API_INTERVAL - time_since_last)
        print(f"\n[RATE LIMIT] Blocked. {BURST_COUNT}/{MAX_BURST_UPDATES} updates used. Reset in {remaining}s.")
        return get_latest_snapshot_time() # Return cache
    
    # Proceed with Fetch
    print(f"\n[{datetime.datetime.now()}] Starting Data Fetch (Burst: {BURST_COUNT+1}/{MAX_BURST_UPDATES})...")
    
    ts = load.timescale(); t_now = ts.now()
    observer = wgs84.latlon(OVRO_LAT, OVRO_LON, elevation_m=OVRO_ALT)
    
    h_az, h_alt, h_dist = get_horizon_offline()
    if h_az: np_h_az, np_h_alt, np_h_dist = np.array(h_az), np.array(h_alt), np.array(h_dist)
    else: np_h_az, np_h_alt, np_h_dist = np.linspace(0, 360, 36), np.zeros(36), np.ones(36)*1e9

    lines = []; headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

    # CelesTrak
    try:
        url = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle'
        r = requests.get(url, headers=headers, timeout=45)
        lines.extend(r.text.strip().splitlines())
    except Exception as e: print(f"CelesTrak Error: {e}")

    # ClassFD
    try:
        url_class = 'https://mmccants.org/tles/classfd.zip'
        r = requests.get(url_class, headers=headers, timeout=45)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            with z.open('classfd.tle') as f:
                lines.extend(f.read().decode('utf-8').strip().splitlines())
    except Exception as e: print(f"ClassFD Error: {e}")

    objs = []; pattern = re.compile(r'^([A-Z]+(?:[-_\s]?[A-Z]+)*)')
    i = 0
    while i < len(lines):
        if lines[i].startswith('1 '): name="Unk"; l1=lines[i]; l2=lines[i+1]; i+=2
        elif i+1<len(lines) and lines[i+1].startswith('1 '): name=lines[i].strip(); l1=lines[i+1]; l2=lines[i+2]; i+=3
        else: i+=1; continue
        try:
            sat = EarthSatellite(l1, l2, name, t_now.ts)
            geo = (sat - observer).at(t_now); alt, az, dist = geo.altaz()
            if alt.degrees > -5:
                if alt.degrees > np.interp(az.degrees, np_h_az, np_h_alt):
                    m = pattern.match(name.upper())
                    gid = m.group(1).strip(' -_') if m else name
                    if len(gid)<2: gid=name
                    objs.append((name, 'sat', gid, az.degrees, alt.degrees, dist.m))
        except: continue

    # Aircraft
    try:
        bbox = [OVRO_LAT-4, OVRO_LON-4, OVRO_LAT+4, OVRO_LON+4]
        url = f"https://opensky-network.org/api/states/all?lamin={bbox[0]}&lomin={bbox[1]}&lamax={bbox[2]}&lomax={bbox[3]}"
        data = requests.get(url, headers=headers, timeout=10).json()
        if data and data.get('states'):
            for p in data['states']:
                if p[5] and p[6] and p[7]:
                    loc = wgs84.latlon(p[6], p[5], elevation_m=p[7])
                    geo = (loc - observer).at(t_now); alt, az, dist = geo.altaz()
                    if alt.degrees > -5:
                        if alt.degrees > np.interp(az.degrees, np_h_az, np_h_alt) or dist.m < np.interp(az.degrees, np_h_az, np_h_dist):
                            objs.append((p[1].strip(), 'plane', 'Aircraft', az.degrees, alt.degrees, dist.m))
    except: pass

    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    ts_val = time.time(); readable = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO snapshots (timestamp, readable_time) VALUES (?, ?)", (ts_val, readable)); sid = c.lastrowid
    if objs:
        c.executemany("INSERT INTO objects (snapshot_id, name, type, group_id, az_deg, alt_deg, dist_m) VALUES (?,?,?,?,?,?,?)", 
                      [(sid, *o) for o in objs])
    conn.commit(); conn.close()
    
    cleanup_old_data()
    
    # Update State Logic
    if BURST_COUNT == 0:
        LAST_FETCH_TIME = now # Anchor the time window to the FIRST fetch
    BURST_COUNT += 1
    
    print(f"Fetch Complete. Snapshot #{sid} saved.\n")
    return readable

def scheduler_loop():
    import schedule
    fetch_job(); schedule.every(FETCH_INTERVAL_MINUTES).minutes.do(fetch_job)
    while True: schedule.run_pending(); time.sleep(1)

# ---------------------------------------------------------
# 3. API ENDPOINTS
# ---------------------------------------------------------

@app.route('/api/history')
def api_history():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT id, timestamp, readable_time FROM snapshots ORDER BY id ASC")
    rows = c.fetchall(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/snapshot/<int:snap_id>')
def api_snapshot(snap_id):
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT * FROM objects WHERE snapshot_id=?", (snap_id,))
    rows = c.fetchall(); conn.close()
    
    objects = [dict(r) for r in rows]
    grouped = {}
    stats = {'sat_count': 0, 'plane_count': 0, 'constellations': {}}
    
    for o in objects:
        gid = o['group_id']
        grouped.setdefault(gid, []).append(o)
        if o['type'] == 'plane': stats['plane_count'] += 1
        else:
            stats['sat_count'] += 1
            stats['constellations'][gid] = stats['constellations'].get(gid, 0) + 1

    top_5 = sorted(stats['constellations'].items(), key=lambda x: x[1], reverse=True)[:5]
    traces = []
    s_groups = sorted(grouped.keys(), key=lambda g: (1 if g in PRIORITY_CONSTELLATIONS else 0, len(grouped[g])), reverse=True)
    
    for g in s_groups:
        sub = grouped[g]
        if g=='Aircraft': c='red'; s='triangle-up'; sz=10; op=1.0
        elif g in PRIORITY_CONSTELLATIONS: conf=PRIORITY_CONSTELLATIONS[g]; c=conf['color']; s=conf['symbol']; sz=conf['size']; op=conf['opacity']
        else: h=int(hashlib.sha256(g.encode()).hexdigest(),16)%360; c=f'hsl({h},70%,50%)'; s='circle'; sz=8; op=0.7
        traces.append({
            'name': g, 'x': [o['az_deg'] for o in sub], 'y': [o['alt_deg'] for o in sub],
            'text': [o['name'] for o in sub], 'marker': {'symbol': s, 'color': c, 'size': sz, 'opacity': op}
        })
        
    return jsonify({'traces': traces, 'stats': {'sat_total': stats['sat_count'], 'plane_total': stats['plane_count'], 'top_constellations': top_5}})

@app.route('/api/sources')
def api_sources():
    snapshot_arg = request.args.get('snapshot')
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    if snapshot_arg == 'latest': c.execute("SELECT id, readable_time FROM snapshots ORDER BY id DESC LIMIT 1")
    else: c.execute("SELECT id, readable_time FROM snapshots ORDER BY id ASC")
    snaps = c.fetchall()
    result = {}
    for s in snaps:
        s_id = s['id']; ts_str = s['readable_time']
        c.execute("SELECT * FROM objects WHERE snapshot_id=?", (s_id,)); objs = c.fetchall()
        snap_data = {"sources": {"airplanes": {}, "satellites": {}}}
        for o in objs:
            obj_name = o['name']
            if o['type'] == 'plane': snap_data["sources"]["airplanes"][obj_name] = {"alt": o['alt_deg'], "az": o['az_deg'], "dist": o['dist_m']}
            else:
                const = o['group_id']
                if const not in snap_data["sources"]["satellites"]: snap_data["sources"]["satellites"][const] = {}
                snap_data["sources"]["satellites"][const][obj_name] = {"alt": o['alt_deg'], "az": o['az_deg']}
        result[ts_str] = snap_data
    conn.close()
    return jsonify(result)

@app.route('/update', methods=['POST'])
def trigger_update():
    try: new_time = fetch_job(); return jsonify({"status": "success", "time": new_time})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

# ---------------------------------------------------------
# 4. MAIN PAGE
# ---------------------------------------------------------
@app.route('/')
def index():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1"); snap = c.fetchone()
    if not snap: snap = {'id': 0, 'readable_time': 'No Data', 'timestamp': time.time()}
    
    c.execute("SELECT COUNT(DISTINCT group_id) FROM objects WHERE snapshot_id=?", (snap['id'],))
    res = c.fetchone()
    group_count = res[0] if res else 0
    conn.close()

    h_az, h_alt, _ = get_horizon_offline()

    fill_light = 'rgba(128, 128, 128, 0.4)'; line_light = dict(color='black', width=1)
    fill_dark = 'rgba(200, 200, 200, 0.25)'; line_dark = dict(color='white', width=1)

    est_rows = math.ceil((group_count + 3) / 4)
    legend_height_px = est_rows * 25
    bottom_margin = legend_height_px + 80
    total_height = 500 + bottom_margin

    # RECTANGULAR
    fig_rect = go.Figure()
    fig_rect.add_hrect(y0=90-(BEAM_WIDTH_DEG/2), y1=90, fillcolor='lime', opacity=0.15, line_width=0, layer="below")
    fig_rect.add_trace(go.Scatter(x=h_az, y=h_alt, mode='lines', line=line_light, fill='tozeroy', fillcolor=fill_light, name='Terrain', visible=True, hoverinfo='skip'))
    fig_rect.add_trace(go.Scatter(x=h_az, y=h_alt, mode='lines', line=line_dark, fill='tozeroy', fillcolor=fill_dark, name='Terrain', visible=False, hoverinfo='skip'))

    fig_rect.update_layout(
        title=f"Rectangular View",
        xaxis=dict(
            range=[0,360], dtick=45, title="Azimuth", 
            ticktext=['N','NE','E','SE','S','SW','W','NW','N'], tickvals=[0,45,90,135,180,225,270,315,360],
            showgrid=True, gridcolor='#dddddd', showline=True, linecolor='black', mirror=True
        ),
        yaxis=dict(
            range=[0,90], title="Altitude",
            showgrid=True, gridcolor='#dddddd', showline=True, linecolor='black', mirror=True
        ),
        height=total_height, margin=dict(t=40, b=bottom_margin, l=40, r=40),
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
    )

    # POLAR
    fig_polar = go.Figure()
    fig_polar.add_trace(go.Barpolar(r=[BEAM_WIDTH_DEG/2], theta=[0], width=[360], marker_color='lime', marker_opacity=0.15, name='Beam', hoverinfo='skip'))
    h_r = [90-a for a in h_alt]; poly_r=list(h_r)+[90]*100; poly_t=list(h_az)+list(np.linspace(360,0,100))
    fig_polar.add_trace(go.Scatterpolar(r=poly_r, theta=poly_t, mode='lines', fill='toself', fillcolor=fill_light, line=line_light, name='Terrain', visible=True, hoverinfo='skip'))
    fig_polar.add_trace(go.Scatterpolar(r=poly_r, theta=poly_t, mode='lines', fill='toself', fillcolor=fill_dark, line=line_dark, name='Terrain', visible=False, hoverinfo='skip'))

    fig_polar.update_layout(
        title="Polar View", 
        polar=dict(
            radialaxis=dict(range=[0,90], showgrid=True, gridcolor='#dddddd', linecolor='black'), 
            angularaxis=dict(
                rotation=90, direction="clockwise", 
                ticktext=['N','E','S','W'], tickvals=[0,90,180,270],
                showgrid=True, gridcolor='#dddddd', linecolor='black'
            ), 
            bgcolor='rgba(0,0,0,0)'
        ),
        height=600, paper_bgcolor='rgba(0,0,0,0)'
    )

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>CASM RFI Sky Monitor</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>
            :root {{ --bg: #f8f9fa; --text: #333; --panel: #fff; --border: #ddd; --dash-bg: #e9ecef; }}
            body.dark {{ --bg: #1a1a1a; --text: #eee; --panel: #2d2d2d; --border: #555; --dash-bg: #3a3a3a; }}
            body {{ background: var(--bg); color: var(--text); font-family: sans-serif; margin: 20px; transition: 0.3s; }}
            .card {{ max-width: 1200px; margin: 0 auto; background: var(--panel); padding: 20px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
            header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 1px solid var(--border); padding-bottom: 15px; }}
            h2 {{ margin: 0; }}
            .controls {{ display: flex; gap: 10px; align-items: center; }}
            .dashboard {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 20px; }}
            .stat-box {{ background: var(--dash-bg); padding: 15px; border-radius: 6px; text-align: center; }}
            .stat-val {{ font-size: 1.8em; font-weight: bold; color: #007bff; display: block; }}
            .stat-label {{ font-size: 0.9em; color: #888; }}
            .const-list {{ text-align: left; font-size: 0.85em; list-style: none; padding: 0; margin: 0; }}
            .const-list li {{ display: flex; justify-content: space-between; padding: 2px 0; border-bottom: 1px solid rgba(0,0,0,0.05); }}
            .player {{ display: flex; gap: 15px; align-items: center; margin-bottom: 15px; background: rgba(0,0,0,0.05); padding: 15px; border-radius: 5px; }}
            input[type=range] {{ flex-grow: 1; }}
            .time-display {{ font-family: monospace; font-size: 0.85em; text-align: right; min-width: 180px; }}
            button {{ padding: 8px 12px; cursor: pointer; border: 1px solid var(--border); border-radius: 4px; background: #eee; color: #333; }}
            body.dark button {{ background: #444; color: #fff; }}
            button.primary {{ background: #007bff; color: white; border: none; }}
            select {{ padding: 8px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <header>
                <div><h2>CASM RFI Sky Monitor</h2><small id="status">OVRO | {snap['readable_time']}</small></div>
                <div class="controls">
                    <button class="primary" onclick="forceUpdate()">Force Update</button>
                    <button onclick="toggleTheme()">Dark Mode</button>
                </div>
            </header>

            <div class="dashboard">
                <div class="stat-box">
                    <span class="stat-val" id="stat-sats">--</span>
                    <span class="stat-label">Visible Satellites</span>
                </div>
                <div class="stat-box">
                    <span class="stat-val" id="stat-planes">--</span>
                    <span class="stat-label">Visible Aircraft</span>
                </div>
                <div class="stat-box">
                    <span class="stat-label" style="display:block; margin-bottom:5px;">Top Constellations</span>
                    <ul class="const-list" id="const-list"><li>Loading...</li></ul>
                </div>
            </div>
            
            <div class="player">
                <button id="play-btn" onclick="togglePlay()">Play</button>
                <button onclick="goToLatest()" title="Jump to latest">Latest</button>
                <input type="range" id="timeline" min="0" max="0" value="0" oninput="scrub(this.value)">
                <select id="history-select" onchange="scrub(this.value)" style="max-width: 150px;"></select>
                <div class="time-display">
                    <div>UTC: <span id="time-utc">--</span></div>
                    <div>LOC: <span id="time-local">--</span></div>
                </div>
            </div>

            <div id="polar"></div>
            <div id="rect"></div>
        </div>
        
        <script>
            var pData = {fig_polar.to_json()};
            var rData = {fig_rect.to_json()};
            var cfg = {{responsive: true}};
            Plotly.newPlot('polar', pData.data, pData.layout, cfg);
            Plotly.newPlot('rect', rData.data, rData.layout, cfg);

            var historyList = [];
            var isPlaying = false;
            var timer = null;
            var currentIndex = 0;
            var isDark = false;

            fetch('/api/history').then(r=>r.json()).then(data => {{
                historyList = data;
                const sel = document.getElementById('history-select');
                historyList.forEach((h, idx) => {{
                    let opt = document.createElement('option');
                    opt.value = idx;
                    opt.text = h.readable_time;
                    sel.appendChild(opt);
                }});
                document.getElementById('timeline').max = historyList.length - 1;
                goToLatest();
            }});

            function goToLatest() {{
                if(isPlaying) togglePlay();
                const latestIdx = historyList.length - 1;
                currentIndex = latestIdx;
                loadSnapshot(currentIndex);
            }}

            function updateDisplayTime(idx) {{
                if(!historyList[idx]) return;
                const ts = historyList[idx].timestamp;
                const date = new Date(ts * 1000);
                document.getElementById('time-utc').textContent = date.toISOString().replace('T', ' ').substring(0, 19);
                document.getElementById('time-local').textContent = date.toLocaleString();
                document.getElementById('timeline').value = idx;
                document.getElementById('history-select').value = idx;
            }}

            function updateDashboard(stats) {{
                document.getElementById('stat-sats').textContent = stats.sat_total;
                document.getElementById('stat-planes').textContent = stats.plane_total;
                const list = document.getElementById('const-list');
                list.innerHTML = '';
                stats.top_constellations.forEach(item => {{
                    let li = document.createElement('li');
                    li.innerHTML = `<span>${{item[0]}}</span> <span>${{item[1]}}</span>`;
                    list.appendChild(li);
                }});
            }}

            function loadSnapshot(idx) {{
                if(!historyList[idx]) return;
                fetch('/api/snapshot/' + historyList[idx].id).then(r=>r.json()).then(resp => {{
                    const traces = resp.traces;
                    updateDisplayTime(idx);
                    updateDashboard(resp.stats);
                    
                    var rectEl = document.getElementById('rect');
                    var staticRect = rectEl.data.slice(0, 3);
                    var newRectTraces = traces.map(t => ({{
                        x: t.x, y: t.y, mode: 'markers', marker: t.marker, name: t.name, type: 'scatter', text: t.text, 
                        hovertemplate: "<b>%{{text}}</b><br>Az: %{{x:.1f}}<br>Alt: %{{y:.1f}}<extra></extra>"
                    }}));
                    var layoutR = rectEl.layout;
                    layoutR.title.text = "Rectangular View - " + historyList[idx].readable_time;
                    Plotly.react('rect', staticRect.concat(newRectTraces), layoutR);

                    var polarEl = document.getElementById('polar');
                    var staticPolar = polarEl.data.slice(0, 3);
                    var newPolarTraces = traces.map(t => ({{
                        r: t.y.map(y=>90-y), theta: t.x, mode: 'markers', marker: t.marker, name: t.name, type: 'scatterpolar', showlegend: false, text: t.text,
                        hovertemplate: "<b>%{{text}}</b><br>Az: %{{theta:.1f}}<br>Alt: %{{customdata:.1f}}<extra></extra>", customdata: t.y
                    }}));
                    Plotly.react('polar', staticPolar.concat(newPolarTraces), polarEl.layout);
                }});
            }}

            function togglePlay() {{
                isPlaying = !isPlaying;
                document.getElementById('play-btn').textContent = isPlaying ? "Pause" : "Play";
                if(isPlaying) {{
                    if(currentIndex >= historyList.length-1) currentIndex = 0;
                    timer = setInterval(() => {{
                        currentIndex++;
                        if(currentIndex >= historyList.length) currentIndex = 0;
                        loadSnapshot(currentIndex);
                    }}, 1500);
                }} else clearInterval(timer);
            }}

            function scrub(val) {{
                currentIndex = parseInt(val);
                if(isPlaying) togglePlay(); 
                loadSnapshot(currentIndex);
            }}

            function forceUpdate() {{
                const btn = document.querySelector('button.primary');
                const orig = btn.textContent;
                btn.disabled = true; btn.textContent = "Updating...";
                fetch('/update', {{method:'POST'}}).then(r=>r.json()).then(()=>{{ location.reload(); }}).catch(e=>{{ alert("Fail: "+e); btn.disabled=false; btn.textContent=orig; }});
            }}

            function toggleTheme() {{
                isDark = !isDark;
                document.body.classList.toggle('dark', isDark);
                var bg = isDark ? '#2d2d2d' : '#fff';
                var txt = isDark ? '#eee' : '#333';
                var grd = isDark ? '#555' : '#ddd';
                var line = isDark ? '#ffffff' : '#000000';
                var vis = isDark ? [false, true] : [true, false]; 
                
                Plotly.relayout('rect', {{
                    'paper_bgcolor':bg, 'plot_bgcolor':bg, 'font.color':txt, 
                    'xaxis.gridcolor':grd, 'yaxis.gridcolor':grd,
                    'xaxis.linecolor':line, 'yaxis.linecolor':line,
                    'xaxis.zerolinecolor':grd, 'yaxis.zerolinecolor':grd
                }});
                Plotly.restyle('rect', 'visible', vis[0], [1]);
                Plotly.restyle('rect', 'visible', vis[1], [2]);
                
                Plotly.relayout('polar', {{
                    'paper_bgcolor':bg, 'font.color':txt, 'polar.bgcolor':bg, 
                    'polar.radialaxis.gridcolor':grd, 'polar.angularaxis.gridcolor':grd,
                    'polar.radialaxis.linecolor':line, 'polar.angularaxis.linecolor':line
                }});
                Plotly.restyle('polar', 'visible', vis[0], [1]);
                Plotly.restyle('polar', 'visible', vis[1], [2]);
            }}
        </script>
    </body>
    </html>
    """
    return html

if __name__ == '__main__':
    init_db(); init_horizon()
    t = threading.Thread(target=scheduler_loop); t.daemon = True; t.start()
    print("Server: http://127.0.0.1:5000")
    app.run(debug=True, use_reloader=False)