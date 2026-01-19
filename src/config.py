"""
Configuration loader for sky RFI Monitor.
Loads and validates configuration from YAML file.
"""

import os
from typing import Any, Dict

import yaml


class Config:
    """Load and provide access to configuration from YAML file."""

    def __init__(self, config_file: str = "config.yaml"):
        self.path = config_file
        self.data: Dict[str, Any] = {}
        self.load()

    def load(self):
        """Load YAML configuration file."""
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"Config file not found: {self.path}")

        with open(self.path, "r", encoding="utf-8") as f:
            self.data = yaml.safe_load(f) or {}

    # Database properties
    @property
    def db_name(self) -> str:
        """Get database file path."""
        db_config = self.data.get("database", {})
        return db_config.get("name", "data/casm_rfi_sky.db")

    @property
    def retention_days(self) -> int:
        """Get data retention period in days."""
        return self.data.get("database", {}).get("retention_days", 7)

    # Cache file properties
    @property
    def tle_cache_file(self) -> str:
        """Get TLE cache file path."""
        cache_config = self.data.get("cache", {})
        default_tle = "data/celestrak_cache.txt"
        return cache_config.get("tle_file", default_tle)

    @property
    def horizon_file(self) -> str:
        """Get horizon profile cache file path."""
        cache_config = self.data.get("cache", {})
        obs_name = self.obs_name
        default_horizon = f"data/{obs_name}_horizon.csv"
        return cache_config.get("horizon_file", default_horizon)

    @property
    def geo_cache_file(self) -> str:
        """Get geospatial data cache file path."""
        cache_config = self.data.get("cache", {})
        return cache_config.get("geo_file", "data/geo_cache.json")

    # OpenSky credentials (deprecated - now using airplanes.live)
    @property
    def opensky_username(self) -> str:
        """Get OpenSky API username (deprecated)."""
        opensky_cfg = self.data.get("opensky", {})
        return opensky_cfg.get("username", "")

    @property
    def opensky_password(self) -> str:
        """Get OpenSky API password (deprecated)."""
        return self.data.get("opensky", {}).get("password", "")

    @property
    def has_opensky_credentials(self) -> bool:
        """Check if OpenSky credentials are configured (deprecated)."""
        return bool(self.opensky_username and self.opensky_password)

    # Timing properties
    @property
    def tle_fetch_interval(self) -> int:
        """Get TLE fetch interval in seconds."""
        return self.data.get("timing", {}).get("tle_fetch_interval", 7200)

    @property
    def plane_fetch_interval(self) -> int:
        """Get aircraft fetch interval in seconds."""
        # Default to 1 second for airplanes.live (no rate limit issues)
        return self.data.get("timing", {}).get("plane_fetch_interval", 1)

    @property
    def db_snapshot_interval(self) -> int:
        """Get database snapshot interval in seconds."""
        return self.data.get("timing", {}).get("db_snapshot_interval", 1800)

    @property
    def live_poll_interval_ms(self) -> int:
        """Get live polling interval in milliseconds."""
        return self.data.get("timing", {}).get("live_poll_interval_ms", 5000)

    # Server properties
    @property
    def dev_host(self) -> str:
        """Get development server host."""
        return self.data.get("server", {}).get("dev_host", "127.0.0.1")

    @property
    def dev_port(self) -> int:
        """Get development server port."""
        return self.data.get("server", {}).get("dev_port", 5000)

    @property
    def prod_host(self) -> str:
        """Get production server host."""
        return self.data.get("server", {}).get("prod_host", "127.0.0.1")

    @property
    def prod_port(self) -> int:
        """Get production server port."""
        return self.data.get("server", {}).get("prod_port", 5000)

    @property
    def prod_workers(self) -> int:
        """Get production gunicorn worker count."""
        return self.data.get("server", {}).get("prod_workers", 4)

    @property
    def live_view_url(self) -> str:
        """Get live view URL (empty string if not configured)."""
        return self.data.get("server", {}).get("live_view_url", "")

    @property
    def observatory(self) -> Dict[str, Any]:
        """Get observatory configuration."""
        return self.data.get("observatory", {})

    @property
    def obs_name(self) -> str:
        """Get observatory name."""
        return self.observatory.get("name", "OVRO")

    @property
    def obs_lat(self) -> float:
        """Get observatory latitude."""
        return self.observatory.get("latitude", 37.2317)

    @property
    def obs_lon(self) -> float:
        """Get observatory longitude."""
        return self.observatory.get("longitude", -118.2951)

    @property
    def obs_alt(self) -> float:
        """Get observatory altitude in meters."""
        return self.observatory.get("altitude_m", 1222)

    # Panorama properties
    @property
    def panorama_id(self) -> str:
        """Get HeyWhatsThat panorama ID."""
        return self.data.get("panorama", {}).get("id", "BTV9VXUH")

    @property
    def panorama_resolution(self) -> str:
        """Get panorama resolution setting."""
        return self.data.get("panorama", {}).get("resolution", "0.1")

    # Visualization properties
    @property
    def beam_width_deg(self) -> float:
        """Get antenna beam width in degrees."""
        return self.data.get("visualization", {}).get("beam_width_deg", 100)

    @property
    def globe_scale_power(self) -> float:
        """Get 3D globe altitude scaling power."""
        viz_cfg = self.data.get("visualization", {})
        return viz_cfg.get("globe_scale_power", 0.45)

    @property
    def plane_search_box_deg(self) -> float:
        """Get aircraft search box size in degrees."""
        viz_cfg = self.data.get("visualization", {})
        return viz_cfg.get("plane_search_box_deg", 4.0)

    # Priority constellations
    @property
    def priority_constellations(self) -> Dict[str, Dict[str, Any]]:
        """Get priority constellation styling configuration."""
        return self.data.get("priority_constellations", {})

    @property
    def default_satellite_style(self) -> Dict[str, Any]:
        """Get default satellite marker styling."""
        default_style = {
            "symbol": "circle",
            "size": 3,
            "opacity": 0.7,
        }
        return self.data.get("default_satellite", default_style)

    # API URLs
    @property
    def apis(self) -> Dict[str, str]:
        """Get API endpoint URLs mapping."""
        return self.data.get("apis", {})

    def get_api_url(self, key: str) -> str:
        """Get API URL by key."""
        return self.apis.get(key, "")

    @property
    def aircraft_source(self) -> str:
        """Get aircraft API source (airplanes_live or opensky)."""
        return self.apis.get("aircraft_source", "airplanes_live")


# Global configuration instance
CONFIG = Config()
