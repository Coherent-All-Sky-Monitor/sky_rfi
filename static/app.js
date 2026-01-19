// CASM rfi Sky Monitor js

// Global state
let geoData = null;
let isDark = true;
let historyList = [];
let CONFIG = {};
let STATIC_TRACES = { rect: [], polar: [] }; // Store initial static traces
let GLOBE_BASE_TRACES = []; // Store globe base traces
let isGlobeInitialized = false; // Track if globe plot exists
let API_TOKEN = ''; // API authentication token
let playbackTimer = null; // Playback interval
let playbackSpeed = 1000; // Playback speed in ms
let statusInterval = null; // Status polling interval
const MONO_FONT = '"SFMono-Regular","Menlo","Consolas","Liberation Mono","Courier New",monospace';

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
  
  // Start status polling
  fetchStatus();
  statusInterval = setInterval(fetchStatus, 1000);
  
  // Load history mode
  loadHistoryList();

  // Apply monospace fonts to plots
  applyMonospacePlots();
}

/**
 * Resize plots to fit container
 */
function resizePlots() {
  try {
    const card = document.querySelector('.card');
    if (!card) return;
    
    const width = card.clientWidth - 40;
    
    // Rect height: 30% of width, min 400px
    const rectHeight = Math.max(400, width * 0.3) + 'px';
    const rectEl = document.getElementById('rect');
    if (rectEl && rectEl.offsetParent !== null) {
      rectEl.style.height = rectHeight;
      try {
        Plotly.Plots.resize(rectEl);
      } catch (e) {
        console.warn('Could not resize rect plot:', e.message);
      }
    }
    
    // Polar height: Square, min 800px
    const sqHeight = Math.max(800, width) + 'px';
    const polarEl = document.getElementById('polar');
    if (polarEl && polarEl.offsetParent !== null) {
      polarEl.style.height = sqHeight;
      try {
        Plotly.Plots.resize(polarEl);
      } catch (e) {
        console.warn('Could not resize polar plot:', e.message);
      }
    }
    
    // Globe height: Same as width (Square), min 800px
    const globeHeight = Math.max(800, width);
    const globeEl = document.getElementById('globe');
    
    if (globeEl && isGlobeInitialized) {
      globeEl.style.height = globeHeight + 'px';
      try {
        Plotly.relayout(globeEl, {width: width, height: globeHeight});
      } catch (e) {
        console.warn('Could not relayout globe plot:', e.message);
      }
    }
  } catch (e) {
    console.warn('resizePlots error:', e.message);
  }
}

/**
 * Load history list from server
 */
function loadHistoryList() {
  fetch('/api/history', {
    headers: { 'X-API-Token': API_TOKEN }
  })
    .then(r => r.json())
    .then(data => {
      historyList = data;
      const sel = document.getElementById('snap-select');
      if (!sel) return;
      
      sel.innerHTML = '';
      data.forEach((h, i) => {
        const opt = document.createElement('option');
        opt.value = i;
        opt.text = h.readable_time;
        sel.add(opt);
      });
      const timeline = document.getElementById('timeline');
      if (timeline) timeline.max = data.length - 1;
      
      if (data.length > 0) {
        loadHistory(data.length - 1);
      } else {
        // Database is empty - wait for initial data fetch, then create first snapshot
        const snapshotTimeEl = document.getElementById('snapshot-time');
        if (snapshotTimeEl) snapshotTimeEl.textContent = 'Waiting for initial data...';
        
        // Poll status until both TLE and aircraft data are fetched
        const waitForData = setInterval(() => {
          fetch('/api/status', {
            headers: { 'X-API-Token': API_TOKEN }
          })
            .then(res => res.json())
            .then(statusData => {
              const hasTLE = statusData.last_tle_fetch && statusData.last_tle_fetch > 0;
              const hasAircraft = statusData.last_aircraft_fetch && statusData.last_aircraft_fetch > 0;
              const timeEl = document.getElementById('snapshot-time');
              
              if (hasTLE && hasAircraft) {
                clearInterval(waitForData);
                if (timeEl) timeEl.textContent = 'Creating first snapshot...';
                forceSnapshot();
              } else if (hasTLE && !hasAircraft) {
                if (timeEl) timeEl.textContent = 'Fetching aircraft data...';
              } else if (!hasTLE) {
                if (timeEl) timeEl.textContent = 'Fetching satellite data...';
              }
            })
            .catch(err => console.error('Status check error:', err));
        }, 1000);
      }
    })
    .catch(err => console.error('loadHistoryList error:', err));
}

/**
 * Load historical snapshot
 * @param {number} idx - Index in history list
 */
function loadHistory(idx) {
  const item = historyList[parseInt(idx)];
  if (!item) return;
  
  // Update snapshot time display
  document.getElementById('snapshot-time').textContent = `Viewing: ${item.readable_time}`;
  
  fetch(`/api/snapshot/${item.id}`, {
    headers: { 'X-API-Token': API_TOKEN }
  })
    .then(r => r.json())
    .then(data => {
      updateUI(data, item.readable_time);
      const timeline = document.getElementById('timeline');
      if (timeline) timeline.value = idx;
      const select = document.getElementById('snap-select');
      if (select) select.value = idx;
      const status = document.getElementById('status');
      if (status) status.textContent = `Snapshot: ${item.readable_time}`;
    })
    .catch(err => console.error('Failed to load snapshot:', err));
}

/**
 * Update UI with data
 * @param {Object} data - Data from API
 * @param {string} timeStr - Timestamp string
 */
function updateUI(data, timeStr) {
  // Check for aircraft API rate limiting
  if (data.aircraft_rate_limit_until) {
    const rateLimitUntil = data.aircraft_rate_limit_until * 1000; // Convert to ms
    const now = Date.now();
    const remaining = Math.ceil((rateLimitUntil - now) / 1000);
    
    console.log(`Rate limit check: until=${rateLimitUntil}, now=${now}, remaining=${remaining}s`);
    
    if (remaining > 0) {
      showAircraftRateLimitBanner(remaining);
    } else {
      // Rate limit has expired, close banner if showing
      if (isAircraftRateLimited) {
        closeBanner();
      }
    }
  } else {
    console.log('No rate limit in data');
  }
  
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
  try {
    isDark = !isDark;
    document.body.classList.toggle('light', !isDark);
    const themeBtn = document.getElementById('theme-btn');
    if (themeBtn) themeBtn.textContent = isDark ? 'Light Mode' : 'Dark Mode';
    
    const txt = isDark ? '#eee' : '#222';
    const grd = isDark ? '#444' : '#ddd';
    const line = isDark ? '#888' : '#333';
    
    const layoutUpdate = {
      'font.family': MONO_FONT,
      'font.color': txt,
      'title.font.color': txt,
      'title.font.family': MONO_FONT,
      'legend.font.color': txt,
      'legend.font.family': MONO_FONT,
      'hoverlabel.font.family': MONO_FONT,
      'hoverlabel.font.color': txt,
      'xaxis.gridcolor': grd,
      'yaxis.gridcolor': grd,
      'xaxis.linecolor': line,
      'yaxis.linecolor': line,
      'xaxis.title.font.color': txt,
      'yaxis.title.font.color': txt,
      'xaxis.title.font.family': MONO_FONT,
      'yaxis.title.font.family': MONO_FONT,
      'polar.radialaxis.tickfont.family': MONO_FONT,
      'polar.angularaxis.tickfont.family': MONO_FONT,
      'polar.radialaxis.tickfont.color': txt,
      'polar.angularaxis.tickfont.color': txt,
      'polar.radialaxis.gridcolor': grd,
      'polar.angularaxis.gridcolor': grd,
      'paper_bgcolor': 'rgba(0,0,0,0)',
      'plot_bgcolor': 'rgba(0,0,0,0)'
    };
    
    ['rect', 'polar', 'globe'].forEach(id => {
      try {
        const el = document.getElementById(id);
        if (el && el.data && el.layout) {
          Plotly.relayout(id, layoutUpdate);
          updateAnnotationsFont(id);
        }
      } catch (e) {
        console.warn(`Could not update theme for ${id}:`, e.message);
      }
    });
    
    // Toggle terrain visibility
    try {
      const rectEl = document.getElementById('rect');
      if (rectEl && rectEl.data && rectEl.data.length > 2) {
        Plotly.restyle('rect', 'visible', isDark, [1]);
        Plotly.restyle('rect', 'visible', !isDark, [2]);
      }
    } catch (e) {
      console.warn('Could not toggle rect terrain:', e.message);
    }
    
    try {
      const polarEl = document.getElementById('polar');
      if (polarEl && polarEl.data && polarEl.data.length > 2) {
        Plotly.restyle('polar', 'visible', isDark, [1]);
        Plotly.restyle('polar', 'visible', !isDark, [2]);
      }
    } catch (e) {
      console.warn('Could not toggle polar terrain:', e.message);
    }
  } catch (e) {
    console.warn('toggleTheme error:', e.message);
  }
}


// Apply monospace font across all plots
function applyMonospacePlots() {
  const fontUpdate = {
    'font.family': MONO_FONT,
    'title.font.family': MONO_FONT,
    'legend.font.family': MONO_FONT,
    'xaxis.title.font.family': MONO_FONT,
    'yaxis.title.font.family': MONO_FONT,
    'hoverlabel.font.family': MONO_FONT,
    'polar.radialaxis.tickfont.family': MONO_FONT,
    'polar.angularaxis.tickfont.family': MONO_FONT,
  };
  ['rect', 'polar', 'globe'].forEach(id => {
    try {
      const el = document.getElementById(id);
      if (el && el.data && el.layout) {
        Plotly.relayout(id, fontUpdate);
        updateAnnotationsFont(id);
      }
    } catch (e) {
      console.warn(`Could not apply monospace to ${id}:`, e.message);
    }
  });
}

// Ensure annotations use monospace font
function updateAnnotationsFont(plotId) {
  try {
    const el = document.getElementById(plotId);
    if (!el || !el.layout) return;
    const anns = el.layout.annotations || [];
    if (!anns.length) return;
    const updated = anns.map(a => ({
      ...a,
      font: { ...(a.font || {}), family: MONO_FONT },
    }));
    Plotly.relayout(plotId, { annotations: updated });
  } catch (e) {
    console.warn(`Could not update annotations for ${plotId}:`, e.message);
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
let rateLimitTimer = null;
let rateLimitEndTime = null;
let aircraftRateLimitTimer = null;
let isAircraftRateLimited = false;

/**
 * Show aircraft API rate limit banner with countdown
 */
function showAircraftRateLimitBanner(waitSeconds) {
  const banner = document.getElementById('rate-limit-banner');
  const message = document.getElementById('banner-message');
  const snapshotBtn = document.getElementById('snapshot-btn');
  
  banner.classList.remove('hidden');
  isAircraftRateLimited = true;
  
  // Disable snapshot button
  snapshotBtn.disabled = true;
  snapshotBtn.title = 'Cannot take snapshot: Aircraft API is rate limited';
  
  const endTime = Date.now() + (waitSeconds * 1000);
  
  // Clear any existing timer
  if (aircraftRateLimitTimer) {
    clearInterval(aircraftRateLimitTimer);
  }
  
  // Update countdown every second
  function updateCountdown() {
    const remaining = Math.ceil((endTime - Date.now()) / 1000);
    
    if (remaining <= 0) {
      closeBanner();
      return;
    }
    
    message.textContent = `Aircraft API rate limited: Data will resume in ${remaining}s (Snapshots disabled)`;
  }
  
  updateCountdown();
  aircraftRateLimitTimer = setInterval(updateCountdown, 1000);
}

/**
 * Show rate limit banner with countdown
 */
function showRateLimitBanner(waitSeconds) {
  const banner = document.getElementById('rate-limit-banner');
  const message = document.getElementById('banner-message');
  
  banner.classList.remove('hidden');
  rateLimitEndTime = Date.now() + (waitSeconds * 1000);
  
  // Clear any existing timer
  if (rateLimitTimer) {
    clearInterval(rateLimitTimer);
  }
  
  // Update countdown every second
  function updateCountdown() {
    const remaining = Math.ceil((rateLimitEndTime - Date.now()) / 1000);
    
    if (remaining <= 0) {
      closeBanner();
      return;
    }
    
    message.textContent = `Rate limited: Please wait ${remaining}s before creating another snapshot`;
  }
  
  updateCountdown();
  rateLimitTimer = setInterval(updateCountdown, 1000);
}

/**
 * Close rate limit banner
 */
function closeBanner() {
  const banner = document.getElementById('rate-limit-banner');
  const snapshotBtn = document.getElementById('snapshot-btn');
  
  banner.classList.add('hidden');
  
  if (rateLimitTimer) {
    clearInterval(rateLimitTimer);
    rateLimitTimer = null;
  }
  
  if (aircraftRateLimitTimer) {
    clearInterval(aircraftRateLimitTimer);
    aircraftRateLimitTimer = null;
    isAircraftRateLimited = false;
    
    // Re-enable snapshot button if it was disabled for aircraft rate limit
    if (snapshotBtn.disabled && snapshotBtn.title.includes('Aircraft API')) {
      snapshotBtn.disabled = false;
      snapshotBtn.title = 'Save current sky view to database';
    }
  }
  
  // Re-enable snapshot button (if it was disabled for snapshot rate limit)
  if (snapshotBtn.textContent.startsWith('Wait')) {
    snapshotBtn.disabled = false;
    snapshotBtn.textContent = 'Snapshot';
  }
}

/**
 * Fetch and display scheduler status
 */
function fetchStatus() {
  fetch('/api/status', {
    headers: { 'X-API-Token': API_TOKEN }
  })
    .then(res => res.json())
    .then(data => {
      const now = Date.now() / 1000;
      
      // Update next snapshot time
      const nextSnapEl = document.getElementById('next-snapshot');
      if (data.next_snapshot_at && data.next_snapshot_at > now) {
        const seconds = Math.ceil(data.next_snapshot_at - now);
        const minutes = Math.floor(seconds / 60);
        const secs = seconds % 60;
        if (minutes > 0) {
          nextSnapEl.textContent = `Next snapshot: ${minutes}m ${secs}s`;
        } else {
          nextSnapEl.textContent = `Next snapshot: ${secs}s`;
        }
      } else {
        nextSnapEl.textContent = 'Next snapshot: < 1s';
      }
      
      // Update force snapshot cooldown
      const cooldownEl = document.getElementById('snapshot-cooldown');
      const snapshotBtn = document.getElementById('snapshot-btn');
      if (data.force_snapshot_available_at && data.force_snapshot_available_at > now) {
        const seconds = Math.ceil(data.force_snapshot_available_at - now);
        cooldownEl.textContent = `Manual snapshot: wait ${seconds}s`;
        cooldownEl.style.color = '#ff6b6b';
        if (snapshotBtn && snapshotBtn.textContent !== 'Saving...') {
          snapshotBtn.disabled = true;
          snapshotBtn.textContent = `Wait ${seconds}s`;
        }
      } else {
        cooldownEl.textContent = 'Manual snapshot: ready';
        cooldownEl.style.color = '#51cf66';
        if (snapshotBtn && snapshotBtn.textContent !== 'Saving...') {
          snapshotBtn.disabled = false;
          snapshotBtn.textContent = 'Snapshot';
        }
      }
      
      // Update timestamp displays
      const formatTimeAgo = (timestamp) => {
        if (!timestamp || timestamp === 0) return 'never';
        const ago = Math.floor(now - timestamp);
        if (ago < 60) return `${ago}s ago`;
        if (ago < 3600) return `${Math.floor(ago / 60)}m ago`;
        return `${Math.floor(ago / 3600)}h ago`;
      };
      
      document.getElementById('last-tle-fetch').textContent = `TLE fetch: ${formatTimeAgo(data.last_tle_fetch)}`;
      document.getElementById('last-aircraft-fetch').textContent = `Aircraft fetch: ${formatTimeAgo(data.last_aircraft_fetch)}`;
      document.getElementById('last-computation').textContent = `Computation: ${formatTimeAgo(data.last_computation)}`;
      
      // Check aircraft rate limit
      if (data.aircraft_rate_limit_until && data.aircraft_rate_limit_until > now) {
        const seconds = Math.ceil(data.aircraft_rate_limit_until - now);
        showAircraftRateLimitBanner(seconds);
      }
    })
    .catch(err => console.error('Status fetch error:', err));
}

/**
 * Force a snapshot to be saved to the database
 */
function forceSnapshot() {
  // Don't allow snapshot if aircraft API is rate limited
  if (isAircraftRateLimited) {
    return;
  }

  // Block if API token is not ready (avoid 403 + parse errors)
  if (!API_TOKEN) {
    console.warn('Snapshot blocked: API token not set yet');
    const btnInit = document.getElementById('snapshot-btn');
    if (btnInit) {
      btnInit.disabled = true;
      btnInit.textContent = 'Waiting for token';
      setTimeout(() => {
        btnInit.textContent = 'Snapshot';
        btnInit.disabled = false;
      }, 1500);
    }
    return;
  }
  
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
    .then(async r => {
      const status = r.status;
      let data = null;
      try {
        data = await r.json();
      } catch (e) {
        // Fallback to text if JSON parsing fails
        try {
          const text = await r.text();
          data = { message: text || `HTTP ${status}` };
        } catch (_) {
          data = { message: `HTTP ${status}` };
        }
      }
      return { status, data, ok: r.ok };
    })
    .then(({ status, data, ok }) => {
      console.log('Snapshot response:', { status, data, ok, dataStatus: data?.status });
      if (status === 429 || data?.status === 'rate_limited') {
        // Rate limited - show banner with countdown and keep button disabled briefly
        const waitSeconds = data?.wait_seconds || 60;
        showRateLimitBanner(waitSeconds);
        btn.textContent = `Wait ${waitSeconds}s`;
        setTimeout(() => {
          btn.textContent = originalText;
          btn.disabled = false;
        }, Math.min(waitSeconds, 5) * 1000); // re-enable quickly; banner handles longer wait
        return;
      }

      // For all other responses, just show a quick status and re-enable
      btn.textContent = (status === 200 && data?.status === 'success') ? 'Saved!' : 'Done';
      setTimeout(() => {
        btn.textContent = originalText;
        btn.disabled = false;
        // Reload history to show new snapshot; ignore errors
        try {
          loadHistoryList();
        } catch (e) {
          console.error('Error loading history after snapshot:', e);
        }
      }, 1200);
    })
    .catch(err => {
      console.error('Snapshot error:', err);
      btn.textContent = 'Error';
      setTimeout(() => {
        btn.textContent = originalText;
        btn.disabled = false;
      }, 2000);
    });
}