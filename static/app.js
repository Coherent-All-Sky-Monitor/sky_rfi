// CASM Sky Monitor - Client-side Application

// Global state
let geoData = null;
let isDark = true;
let historyList = [];
let liveTimer = null;
let CONFIG = {};
let STATIC_TRACES = { rect: [], polar: [] }; // Store initial static traces
let GLOBE_BASE_TRACES = []; // Store globe base traces
let isGlobeInitialized = false; // Track if globe plot exists
let API_TOKEN = ''; // API authentication token
let playbackTimer = null; // Playback interval
let playbackSpeed = 1000; // Playback speed in ms
let currentMode = 'live'; // Track current mode

/**
 * Initialize the application
 * @param {Object} config - Configuration object from server
 */
function initApp(config) {
  CONFIG = config;
  API_TOKEN = config.api_token;
  
  // Capture initial static traces (beam + 2 terrain variants)
  const rectEl = document.getElementById('rect');
  const polarEl = document.getElementById('polar');
  if (rectEl && rectEl.data) STATIC_TRACES.rect = rectEl.data.slice(0, 3);
  if (polarEl && polarEl.data) STATIC_TRACES.polar = polarEl.data.slice(0, 3);
  
  // Load geospatial data
  fetch('/api/geo', {
    headers: { 'X-API-Token': API_TOKEN }
  })
    .then(r => r.json())
    .then(d => {
      geoData = d;
      rebuildGlobeBase();
    })
    .catch(err => console.error('Failed to load geo data:', err));
  
  // Setup camera for globe
  const R = 6371;
  const LAT = CONFIG.obs_lat * Math.PI / 180;
  const LON = CONFIG.obs_lon * Math.PI / 180;
  const ox = R * Math.cos(LAT) * Math.cos(LON);
  const oy = R * Math.cos(LAT) * Math.sin(LON);
  const oz = R * Math.sin(LAT);
  const norm = Math.sqrt(ox * ox + oy * oy + oz * oz);
  const camEye = { x: (ox / norm) * 1.3, y: (oy / norm) * 1.3, z: (oz / norm) * 1.3 };
  
  // Safe update of camera
  if (isGlobeInitialized) {
      Plotly.relayout('globe', { 'scene.camera.eye': camEye });
  } else if (window.GLOBE_DATA) {
      // Pre-update the layout configuration for when it initializes
      if (!window.GLOBE_DATA.layout.scene) window.GLOBE_DATA.layout.scene = {};
      if (!window.GLOBE_DATA.layout.scene.camera) window.GLOBE_DATA.layout.scene.camera = {};
      window.GLOBE_DATA.layout.scene.camera.eye = camEye;
  }
  
  // Initialize UI
  window.addEventListener('resize', resizePlots);
  setTimeout(resizePlots, 500);
  
  // Start clock updates
  updateClock();
  setInterval(updateClock, 1000);
  
  // Start in live mode
  setMode('live');
}

/**
 * Resize plots to fit container
 */
function resizePlots() {
  const card = document.querySelector('.card');
  if (!card) return;
  
  const width = card.clientWidth - 40;
  
  // Rect height: 30% of width, min 400px
  const rectHeight = Math.max(400, width * 0.3) + 'px';
  document.getElementById('rect').style.height = rectHeight;
  
  // Polar height: Square, min 800px
  const sqHeight = Math.max(800, width) + 'px';
  document.getElementById('polar').style.height = sqHeight;
  
  // Globe height: Same as width (Square), min 800px
  const globeHeight = Math.max(800, width);
  const globeEl = document.getElementById('globe');
  
  if (globeEl && isGlobeInitialized) {
    globeEl.style.height = globeHeight + 'px';
    Plotly.relayout(globeEl, {width: width, height: globeHeight});
  }
  
  Plotly.Plots.resize(document.getElementById('rect'));
  Plotly.Plots.resize(document.getElementById('polar'));
}

/**
 * Switch between live and history mode
 * @param {string} mode - 'live' or 'history'
 */
function setMode(mode) {
  currentMode = mode;
  document.getElementById('btn-live').classList.toggle('active', mode === 'live');
  document.getElementById('btn-hist').classList.toggle('active', mode === 'history');
  document.getElementById('history-controls').style.display = mode === 'history' ? 'block' : 'none';
  
  // Show/hide globe tab based on mode
  const globeTab = document.getElementById('globe-tab');
  if (mode === 'history') {
    globeTab.style.display = 'block';
  } else {
    globeTab.style.display = 'none';
    // Switch to rect view if globe is active
    if (document.getElementById('globe').classList.contains('active')) {
      setTab('rect');
    }
  }
  
  // Stop playback when switching modes
  stopPlayback();
  
  if (mode === 'live') {
    fetchLive();
    if (!liveTimer) {
      liveTimer = setInterval(fetchLive, CONFIG.live_poll_interval_ms);
    }
  } else {
    clearInterval(liveTimer);
    liveTimer = null;
    
    fetch('/api/history', {
      headers: { 'X-API-Token': API_TOKEN }
    })
      .then(r => r.json())
      .then(data => {
        historyList = data;
        const sel = document.getElementById('snap-select');
        sel.innerHTML = '';
        data.forEach((h, i) => {
          const opt = document.createElement('option');
          opt.value = i;
          opt.text = h.readable_time;
          sel.add(opt);
        });
        document.getElementById('timeline').max = data.length - 1;
        if (data.length > 0) {
          loadHistory(data.length - 1);
        }
      })
      .catch(err => console.error('Failed to load history:', err));
  }
}

/**
 * Fetch live data from server
 */
function fetchLive() {
  fetch('/api/live', {
    headers: { 'X-API-Token': API_TOKEN }
  })
    .then(r => r.json())
    .then(data => {
      updateUI(data, data.time_str);
      document.getElementById('status').textContent = `${CONFIG.obs_name} - LIVE MODE`;
    })
    .catch(err => {
      console.error('Fetch error:', err);
      document.getElementById('status').textContent = 'Connection Error';
    });
}

/**
 * Load historical snapshot
 * @param {number} idx - Index in history list
 */
function loadHistory(idx) {
  const item = historyList[parseInt(idx)];
  if (!item) return;
  
  fetch(`/api/snapshot/${item.id}`, {
    headers: { 'X-API-Token': API_TOKEN }
  })
    .then(r => r.json())
    .then(data => {
      updateUI(data, item.readable_time);
      document.getElementById('timeline').value = idx;
      document.getElementById('snap-select').value = idx;
      document.getElementById('status').textContent = `${CONFIG.obs_name} - HISTORY MODE`;
    })
    .catch(err => console.error('Failed to load snapshot:', err));
}

/**
 * Update UI with data
 * @param {Object} data - Data from API
 * @param {string} timeStr - Timestamp string
 */
function updateUI(data, timeStr) {
  // Update stats
  document.getElementById('stat-sats').textContent = data.stats.sat_count;
  document.getElementById('stat-planes').textContent = data.stats.plane_count;
  
  if (data.stats.planes_blocked !== undefined) {
    document.getElementById('stat-blocked').textContent = `Blocked: ${data.stats.planes_blocked}`;
  }
  
  // Update constellation list
  const list = document.getElementById('const-list');
  list.innerHTML = '';
  if (data.top) {
    data.top.forEach(item => {
      const li = document.createElement('li');
      li.innerHTML = `<span>${item[0]}</span> <span>${item[1]}</span>`;
      list.appendChild(li);
    });
  }
  
  // Calculate dynamic heights for legend
  const numGroups = data.traces_2d.length;
  const rows = Math.ceil(numGroups / 4);
  const legendH = Math.max(50, rows * 25);
  const bottomMargin = legendH + 60;
  
  // Get current width for responsive sizing
  const card = document.querySelector('.card');
  const width = card ? card.clientWidth - 40 : 800;
  
  // Update 2D plots
  ['rect', 'polar'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    
    // Set height based on plot type
    if (id === 'rect') {
      el.style.height = (width * 0.3) + 'px';
    } else {
      el.style.height = width + 'px';
    }
    
    // Use stored static traces (always the first 3: beam + 2 terrain variants)
    const staticTraces = STATIC_TRACES[id] || [];
    const newTraces = data.traces_2d.map(t => ({
      ...t,
      type: id === 'polar' ? 'scatterpolar' : 'scatter',
      r: id === 'polar' ? t.y.map(y => 90 - y) : undefined,
      theta: id === 'polar' ? t.x : undefined,
      hovertemplate: id === 'polar' 
        ? '<b>%{text}</b><br>Az: %{theta:.1f}<br>Alt: %{customdata:.1f}<extra></extra>'
        : '<b>%{text}</b><br>Az: %{x:.1f}<br>Alt: %{y:.1f}<extra></extra>',
      customdata: id === 'polar' ? t.y : undefined
    }));
    
    // Merge layout updates
    const updatedLayout = Object.assign({}, el.layout, {
      'title.text': timeStr,
      'margin.b': bottomMargin,
      'legend.orientation': 'h',
      'legend.y': -0.2
    });
    
    // Completely rebuild plot with static traces + new data only
    Plotly.newPlot(id, staticTraces.concat(newTraces), updatedLayout);
  });
  
  // Update 3D globe
  const globeEl = document.getElementById('globe');
  
  // Save most recent data for lazy loading
  if (data && data.traces_3d) {
     window.LATEST_GLOBE_TRACES = data.traces_3d;
     window.LATEST_TIME_STR = timeStr;
  }
  
  // FIX: Only update globe if it is initialized and visible, otherwise skip
  if (!globeEl || !isGlobeInitialized) return;
  
  const new3D = data.traces_3d || [];
  let currentBase = GLOBE_BASE_TRACES;
  
  // If we don't have base traces cached yet, try to get from plot or rebuild
  if (currentBase.length === 0 && globeEl.data) {
      currentBase = globeEl.data.filter(t => 
        ['EarthSurface', 'World', 'USA', 'OVRO', 'Zenith'].includes(t.name)
      );
  }
  
  // If still no base, rebuild it? Or just Plot defaults.
  // rebuildGlobeBase handles async, we can't wait here easily.
  // But if isGlobeInitialized is true, GLOBE_BASE_TRACES *should* be populated 
  // because setTab calls it or rebuildGlobeBase populated it.
  
  Plotly.react('globe', currentBase.concat(new3D), Object.assign({}, globeEl.layout, {
       'title.text': timeStr
  }));
}


/**
 * Rebuild globe with base layers (earth, geo, observer)
 */
function rebuildGlobeBase() {
  const traces = [];
  const R = 6371;
  
  // Create earth surface
  const phi = [];
  const theta = [];
  for (let i = 0; i <= 30; i++) phi.push((i * 2 * Math.PI) / 30);
  for (let i = 0; i <= 15; i++) theta.push((i * Math.PI) / 15);
  
  const xe = [];
  const ye = [];
  const ze = [];
  for (let t of theta) {
    const rX = [];
    const rY = [];
    const rZ = [];
    for (let p of phi) {
      rX.push(R * Math.sin(t) * Math.cos(p));
      rY.push(R * Math.sin(t) * Math.sin(p));
      rZ.push(R * Math.cos(t));
    }
    xe.push(rX);
    ye.push(rY);
    ze.push(rZ);
  }
  
  traces.push({
    type: 'surface',
    x: xe,
    y: ye,
    z: ze,
    showscale: false,
    opacity: 0.5,
    colorscale: [
      [0, '#001133'],
      [1, '#001133']
    ],
    hoverinfo: 'skip',
    name: 'EarthSurface'
  });
  
  // Add geospatial data
  if (geoData) {
    traces.push({
      type: 'scatter3d',
      mode: 'lines',
      x: geoData.world.x,
      y: geoData.world.y,
      z: geoData.world.z,
      line: { color: '#00FFFF', width: 2 },
      hoverinfo: 'skip',
      name: 'World'
    });
    traces.push({
      type: 'scatter3d',
      mode: 'lines',
      x: geoData.usa.x,
      y: geoData.usa.y,
      z: geoData.usa.z,
      line: { color: '#00FFFF', width: 1 },
      hoverinfo: 'skip',
      name: 'USA'
    });
  }
  
  // Add observer location
  const LAT = CONFIG.obs_lat * Math.PI / 180;
  const LON = CONFIG.obs_lon * Math.PI / 180;
  const ox = R * Math.cos(LAT) * Math.cos(LON);
  const oy = R * Math.cos(LAT) * Math.sin(LON);
  const oz = R * Math.sin(LAT);
  
  traces.push({
    type: 'scatter3d',
    mode: 'markers',
    x: [ox],
    y: [oy],
    z: [oz],
    marker: { size: 6, color: 'red' },
    name: CONFIG.obs_name || 'OVRO'
  });
  
  // Add zenith line
  traces.push({
    type: 'scatter3d',
    mode: 'lines',
    x: [0, ox * 1.5],
    y: [0, oy * 1.5],
    z: [0, oz * 1.5],
    line: { color: 'red', width: 4 },
    name: 'Zenith'
  });
  
  const globeEl = document.getElementById('globe');
  
  // Store traces for later use
  GLOBE_BASE_TRACES = traces;
  
  if (!globeEl || !isGlobeInitialized) return;
  
  const currentSats = (globeEl.data || []).filter(t => 
    t.mode === 'markers' && t.name !== CONFIG.obs_name && t.name !== 'OVRO'
  );
  Plotly.react('globe', traces.concat(currentSats), globeEl.layout);
}

/**
 * Switch active tab
 * @param {string} id - View panel ID
 */
function setTab(id) {
  document.querySelectorAll('.view-panel').forEach(e => e.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(e => e.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  if (event && event.target) {
      event.target.classList.add('active');
  }
  
  if (id === 'globe') {
      if (!isGlobeInitialized && window.GLOBE_DATA) {
          // First-time initialization (NOW visible)
          const gData = window.GLOBE_DATA;
          
          Plotly.newPlot('globe', gData.data, gData.layout, {responsive: true})
            .then(() => {
                isGlobeInitialized = true;
                
                // If we have fresher data from live updates, apply it now
                let traces = GLOBE_BASE_TRACES;
                let layoutUpdate = {};
                
                if (window.LATEST_GLOBE_TRACES) {
                    traces = traces.concat(window.LATEST_GLOBE_TRACES);
                }
                if (window.LATEST_TIME_STR) {
                    layoutUpdate['title.text'] = window.LATEST_TIME_STR;
                }
                
                if (traces.length > 0) {
                     Plotly.react('globe', traces, Object.assign({}, gData.layout, layoutUpdate));
                }
                
                resizePlots();
            });
      } else {
          // Already initialized, just resize
          requestAnimationFrame(resizePlots);
      }
  } else {
      requestAnimationFrame(resizePlots);
  }
}

/**
 * Toggle dark/light theme
 */
function toggleTheme() {
  isDark = !isDark;
  document.body.classList.toggle('light', !isDark);
  document.getElementById('theme-btn').textContent = isDark ? 'Light Mode' : 'Dark Mode';
  
  const txt = isDark ? '#eee' : '#222';
  const grd = isDark ? '#444' : '#ddd';
  const line = isDark ? '#888' : '#333';
  
  const layoutUpdate = {
    'font.color': txt,
    'title.font.color': txt,
    'legend.font.color': txt,
    'xaxis.gridcolor': grd,
    'yaxis.gridcolor': grd,
    'xaxis.linecolor': line,
    'yaxis.linecolor': line,
    'xaxis.title.font.color': txt,
    'yaxis.title.font.color': txt,
    'polar.radialaxis.gridcolor': grd,
    'polar.angularaxis.gridcolor': grd,
    'paper_bgcolor': 'rgba(0,0,0,0)',
    'plot_bgcolor': 'rgba(0,0,0,0)'
  };
  
  ['rect', 'polar', 'globe'].forEach(id => {
    const el = document.getElementById(id);
    if (el) Plotly.relayout(id, layoutUpdate);
  });
  
  // Toggle terrain visibility
  const rectEl = document.getElementById('rect');
  const polarEl = document.getElementById('polar');
  if (rectEl) {
    Plotly.restyle('rect', 'visible', isDark, [1]);
    Plotly.restyle('rect', 'visible', !isDark, [2]);
  }
  if (polarEl) {
    Plotly.restyle('polar', 'visible', isDark, [1]);
    Plotly.restyle('polar', 'visible', !isDark, [2]);
  }
}

/**
 * Playback controls
 */
function playbackToggle() {
  if (playbackTimer) {
    stopPlayback();
  } else {
    startPlayback();
  }
}

function startPlayback() {
  const btn = document.getElementById('play-btn');
  btn.textContent = 'Pause'; // Text instead of symbol
  playbackTimer = setInterval(() => {
    playbackNext();
  }, playbackSpeed);
}

function stopPlayback() {
  if (playbackTimer) {
    clearInterval(playbackTimer);
    playbackTimer = null;
    const btn = document.getElementById('play-btn');
    btn.textContent = 'Play'; // Text instead of symbol
  }
}

function playbackPrev() {
  const timeline = document.getElementById('timeline');
  const idx = Math.max(0, parseInt(timeline.value) - 1);
  timeline.value = idx;
  loadHistory(idx);
}

function playbackNext() {
  const timeline = document.getElementById('timeline');
  const idx = parseInt(timeline.value) + 1;
  if (idx >= historyList.length) {
    stopPlayback(); // Stop at end
    return;
  }
  timeline.value = idx;
  loadHistory(idx);
}

function setPlaybackSpeed(speed) {
  playbackSpeed = parseInt(speed);
  if (playbackTimer) {
    stopPlayback();
    startPlayback();
  }
}

/**
 * Update UTC and local time displays
 */
function updateClock() {
  const now = new Date();
  
  // UTC time
  const utcHours = String(now.getUTCHours()).padStart(2, '0');
  const utcMinutes = String(now.getUTCMinutes()).padStart(2, '0');
  const utcSeconds = String(now.getUTCSeconds()).padStart(2, '0');
  document.getElementById('utc-time').textContent = `UTC: ${utcHours}:${utcMinutes}:${utcSeconds}`;
  
  // OVRO time (America/Los_Angeles)
  try {
    const ovroTime = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/Los_Angeles',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    }).format(now);
    document.getElementById('local-time').textContent = `OVRO: ${ovroTime}`;
  } catch (e) {
    // Fallback if timezone not supported
    const localHours = String(now.getHours()).padStart(2, '0');
    const localMinutes = String(now.getMinutes()).padStart(2, '0');
    const localSeconds = String(now.getSeconds()).padStart(2, '0');
    document.getElementById('local-time').textContent = `Local: ${localHours}:${localMinutes}:${localSeconds}`;
  }
}
/**
 * Force a snapshot to be saved to the database
 */
function forceSnapshot() {
  const btn = document.getElementById('snapshot-btn');
  const originalText = btn.textContent;
  
  // Disable button during request
  btn.disabled = true;
  btn.textContent = 'Saving...';
  
  fetch('/api/force_snapshot', {
    method: 'POST',
    headers: {
      'X-API-Token': API_TOKEN,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ wait_for_aircraft: true })
  })
    .then(r => r.json().then(data => ({ status: r.status, data })))
    .then(({ status, data }) => {
      if (status === 200) {
        // Success
        btn.textContent = 'Saved!';
        document.getElementById('status').textContent = data.message;
        setTimeout(() => {
          btn.textContent = originalText;
          btn.disabled = false;
        }, 2000);
      } else if (status === 429) {
        // Rate limited
        btn.textContent = `Wait ${data.wait_seconds}s`;
        document.getElementById('status').textContent = data.message;
        setTimeout(() => {
          btn.textContent = originalText;
          btn.disabled = false;
        }, data.wait_seconds * 1000);
      } else {
        // Error
        btn.textContent = 'Failed';
        document.getElementById('status').textContent = data.message || 'Snapshot failed';
        setTimeout(() => {
          btn.textContent = originalText;
          btn.disabled = false;
        }, 2000);
      }
    })
    .catch(err => {
      console.error('Snapshot error:', err);
      btn.textContent = 'Error';
      document.getElementById('status').textContent = 'Network error';
      setTimeout(() => {
        btn.textContent = originalText;
        btn.disabled = false;
      }, 2000);
    });
}