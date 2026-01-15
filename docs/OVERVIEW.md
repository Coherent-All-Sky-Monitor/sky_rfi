# Architecture Overview

The CASM RFI Sky Monitor consists of several key components:

## Components

### Frontend (Web Interface)
- Interactive 2D and 3D visualizations
- Real-time data updates via polling
- Responsive design for multiple devices

### Backend (Flask API)
- REST endpoints for position data
- Historical snapshot access
- Real-time live data streaming

### Data Processing
- Satellite position calculations using Skyfield
- Aircraft tracking via OpenSky Network
- Horizon visibility masking
- 3D coordinate transformations

### Data Storage
- SQLite database for snapshots
- Cache files for TLE data and horizon profiles
- GeoJSON data for map overlays

### Scheduling
- Background thread for periodic TLE updates
- Aircraft position refresh cycles
- Automatic snapshot saving

## Data Flow

1. **TLE Acquisition**: Download satellite data from CelesTrak
2. **Position Calculation**: Calculate positions relative to observer
3. **Visibility Determination**: Check if objects are above horizon
4. **Snapshot Storage**: Periodically save visible objects to database
5. **Visualization**: Display on interactive web interface
6. **API Access**: Expose data via REST endpoints

## Configuration

All settings are configured via `config.yaml`:

- **Observatory Location**: Latitude, longitude, altitude
- **Horizon Profile**: Panorama ID from HeyWhatsThat
- **API Credentials**: OpenSky Network credentials (optional)
- **Cache Locations**: TLE, horizon, and geospatial data paths
- **Update Intervals**: Timing for data refreshes
- **Server Settings**: Host, port, worker configuration

## Visibility Calculation

An object is visible if:

1. **Altitude Check**: Above the horizon (accounting for terrain)
2. **Aircraft Distance Check**: Closer than horizon obstruction distance (aircraft only)

The horizon profile is interpolated at the object's azimuth to determine the minimum altitude for visibility.

## Technologies

- **Backend**: Flask, Skyfield, NumPy
- **Frontend**: Plotly, JavaScript
- **Data**: SQLite, YAML, GeoJSON
- **APIs**: OpenSky Network, CelesTrak, HeyWhatsThat
