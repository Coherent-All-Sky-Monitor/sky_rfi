# Configuration

All settings are stored in `config.yaml`. The configuration is organized into several sections:

## Database Settings

```yaml
database:
  name: "data/casm_rfi_sky.db"
  retention_days: 7
```

- `name`: Path to SQLite database file
- `retention_days`: Number of days to keep snapshots

## Cache Files

```yaml
cache:
  tle_file: "data/celestrak_cache.txt"
  horizon_file: "data/CASM_horizon.csv"
  geo_file: "data/geo_cache.json"
```

- `tle_file`: Cached satellite TLE data
- `horizon_file`: Horizon profile data from HeyWhatsThat
- `geo_file`: GeoJSON data for map visualization

## OpenSky Network

```yaml
opensky:
  username: ""
  password: ""
```

Leave empty for anonymous access (limited to 400 calls/hour).
Register at https://opensky-network.org for higher limits.

## Timing Configuration

```yaml
timing:
  tle_fetch_interval: 7200        # 2 hours
  plane_fetch_interval: 300       # 5 minutes
  db_snapshot_interval: 1800      # 30 minutes
  live_poll_interval_ms: 2500     # 2.5 seconds
```

- `tle_fetch_interval`: How often to refresh satellite TLE data
- `plane_fetch_interval`: How often to fetch aircraft positions
- `db_snapshot_interval`: How often to save snapshots to database
- `live_poll_interval_ms`: Frontend refresh rate (milliseconds)

## Server Configuration

```yaml
server:
  dev_host: "0.0.0.0"
  dev_port: 5666
  prod_host: "0.0.0.0"
  prod_port: 9893
  prod_workers: 4
```

- `dev_host`, `dev_port`: Development server settings
- `prod_host`, `prod_port`: Production server settings
- `prod_workers`: Number of Gunicorn worker processes

## Observatory Settings

```yaml
observatory:
  name: "CASM"
  latitude: 37.2317
  longitude: -118.2951
  altitude_m: 1222
```

Enter your observatory's exact coordinates and altitude.

## Panorama Settings

```yaml
panorama:
  id: "BTV9VXUH"
  resolution: "0.1"
```

Get your panorama ID from https://www.heywhatsthat.com/

- `id`: Your unique panorama identifier
- `resolution`: Degrees per point (lower = more detail, slower)

## Visualization Settings

```yaml
visualization:
  beam_width_deg: 100
  globe_scale_power: 0.3
  plane_search_box_deg: 4.0
```

- `beam_width_deg`: Width of observation beam for visualization
- `globe_scale_power`: Power function for scaling altitudes on 3D globe
- `plane_search_box_deg`: Search radius around observatory for aircraft (degrees)

## Setting Up Your Observatory

### 1. Get Observatory Coordinates

Use GPS or mapping service to get precise latitude/longitude/altitude

### 2. Create HeyWhatsThat Panorama

- Visit https://www.heywhatsthat.com/
- Create a panorama at your location
- Note the panorama ID

### 3. Update config.yaml

```yaml
observatory:
  name: "YOUR_OBSERVATORY_NAME"
  latitude: YOUR_LAT
  longitude: YOUR_LON
  altitude_m: YOUR_ALT

panorama:
  id: "YOUR_PANORAMA_ID"
```

### 4. Test Configuration

```bash
make test
```

## Environment Variables

Override configuration via environment variables (optional):

```bash
export FLASK_DEBUG=1
export FLASK_ENV=development
make dev
```
