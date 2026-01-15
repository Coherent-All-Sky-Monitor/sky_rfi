# CASM sky RFI Monitor

Real-time visualization of satellites and aircraft above the horizon at an observatory location.


## Installation

Using the included Makefile:

```bash
# 1. Install (creates virtual environment and installs dependencies)
make install

# Or use uv for faster installation (if you have uv installed)
make install-uv

# 2. Check Python 3.8+ compatibility
make check-compat

# 3. Run in development mode
make dev

# 4. Or run in production mode
make prod
```

### Server Configuration

Control the server address and port:

```bash
# Development mode on custom IP and port
make dev HOST=0.0.0.0 PORT=8080

# Production mode on different port
make prod PORT=3000

# Production with gunicorn, custom workers
make prod-gunicorn HOST=0.0.0.0 PORT=8000 WORKERS=8
```

Default values:
- `HOST=127.0.0.1` (localhost only)
- `PORT=5000`
- `WORKERS=4` (gunicorn only)

### Manual Installation

1. **Clone or navigate to the project directory**
   ```bash
   cd /Users/pranav/git/casm/casm_rfi_sky
   ```

2. **Create virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Running the Application

### Using Makefile (Easiest)
```bash
make dev         # Development mode with auto-reload
make prod        # Production mode (gunicorn)
```

### Manual Execution

**Development Mode:**
```bash
source venv/bin/activate
python app.py
```

**Production Mode:**
```bash
source venv/bin/activate

# Using gunicorn (Unix/Linux/macOS)
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

Then open: http://127.0.0.1:5000

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make install` | Create venv and install all dependencies |
| `make install-uv` | Install using uv (faster, requires uv) |
| `make check-compat` | Check Python 3.8+ compatibility |
| `make dev` | Run development server with auto-reload |
| `make prod` | Run production server (gunicorn) |
| `make test` | Test installation and dependencies |
| `make status` | Check installation status |
| `make clean` | Remove venv and cache files |
| `make clean-data` | Clear cached data (keeps database) |
| `make help` | Show all available commands |


## Configuration

All settings are in `config.yaml`:

```yaml
# Example: Change observatory location
observatory:
  name: "My Observatory"
  latitude: 40.7128
  longitude: -74.0060
  altitude_m: 10

# Example: Add OpenSky credentials for faster updates
opensky:
  username: "your_username"
  password: "your_password"

# Example: Customize priority constellations
priority_constellations:
  STARLINK:
    color: "#00ffff"
    symbol: "circle"
    size: 3
    opacity: 0.8
```

## Data Sources

- **Satellites**: CelesTrakm McCants classified (TLE data)
- **Aircraft**: OpenSky Network
- **Horizon**: HeyWhatsThat panorama API
- **Geospatial**: World and USA boundary data

## Public API

The following endpoints are available for public access (no authentication required):

### 1. Latest Positions
Returns current positions of all tracked satellites and aircraft.

**Endpoint:** `GET /api/public/latest`

**Response:**
```json
{
    "2026-01-14 19:30:00": {
        "airplanes": {
            "UAL123": { "alt": 10500, "az": 45.2, "distance": 12500.5 }
        },
        "satellites": {
            "STARLINK": {
                "constellation_name": "STARLINK",
                "list": {
                    "STARLINK-1234": { "alt": 45.0, "az": 180.0 }
                }
            }
        }
    }
}
```
*Note: Altitude (alt) and Azimuth (az) are in degrees. Distance is in meters.*

### 2. List Snapshots
Returns a list of available historical snapshots.

**Endpoint:** `GET /api/public/snapshots`

**Response:**
```json
[
    {
        "id": 1,
        "timestamp": "2026-01-14 19:00:00"
    },
    ...
]
```

### 3. Get Snapshot
Returns data for a specific historical snapshot.

**Endpoint:** `GET /api/public/snapshot/<id>`

**Response:** Same format as `/api/public/latest` but includes `snapshot_id`.

```json
{
    "2026-01-14 19:00:00": {
        "snapshot_id": 123,
        "airplanes": { ... },
        "satellites": { ... }
    }
}
```
## Documentation

Build and view the Sphinx documentation locally:

```bash
# Build documentation from docstrings
make docs

# Serve documentation at http://localhost:8000
make docs-serve

# Clean documentation build artifacts
make docs-clean
```

### GitHub Pages Deployment

Documentation is automatically built and deployed to GitHub Pages on every push to `main`.

**To enable GitHub Pages:**

1. Go to repository **Settings → Pages**
2. Under **Build and deployment**, select:
   - **Source**: GitHub Actions
   - **Branch**: (no selection needed, GitHub Actions handles this)

3. The workflow at `.github/workflows/docs.yml` will automatically:
   - Generate API documentation from docstrings using `sphinx-apidoc`
   - Build HTML documentation using `sphinx-build`
   - Deploy to GitHub Pages using `peaceiris/actions-gh-pages`

**View deployed documentation:**
- GitHub Pages URL: `https://username.github.io/repository-name/`
- Or if custom domain is set in `.github/workflows/docs.yml` under `cname`

**Documentation sources:**
- Manual docs: `docs/*.rst` (overview, installation, configuration, etc.)
- API docs: Auto-generated from `src/` module docstrings
## Maintenance

### Clear Cache
```bash
rm data/*.txt data/*.json data/*.csv
```

### Reset Database
```bash
rm data/*.db
```

### Update TLE Data Manually
```bash
rm data/celestrak_cache.txt
# Will auto-download on next fetch
```

## Troubleshooting

**OpenSky Rate Limiting**
- Add credentials to `config.yaml` for higher rate limits
- Or increase `plane_fetch_interval` to reduce API calls

**Database Locked**
- Stop all instances of the app
- Delete `data/*.db-wal` and `data/*.db-shm` files

## License

MIT
