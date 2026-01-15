"""
API clients for fetching data from external sources.
Handles TLE data, aircraft positions, horizon profiles, and geospatial data.
"""

import csv
import io
import json
import math
import os
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import requests
from skyfield.api import load
from skyfield.sgp4lib import EarthSatellite

from src.config import CONFIG
from src.utils import log


class TLEClient:
    """Fetch and parse Two-Line Element (TLE) data for satellites."""

    def __init__(self):
        self.cache_file = CONFIG.tle_cache_file
        self.fetch_interval = CONFIG.tle_fetch_interval
        self.celestrak_url = CONFIG.get_api_url("celestrak_tle")
        self.mccants_url = CONFIG.get_api_url("mccants_classfd")

    def fetch_tles(self) -> List[Dict[str, Any]]:
        """
        Fetch TLE data from CelesTrak or local cache.

        Returns:
            List of dicts with 'sat' (EarthSatellite),
            'name', and 'group' keys
        """
        log("TLE", "Checking CelesTrak data...")
        lines = []
        cache_valid = False

        # Check cache
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()
            except OSError as e:
                log("TLE", f"Cache read error: {e}")

            age = time.time() - os.path.getmtime(self.cache_file)
            if age < self.fetch_interval:
                cache_msg = f"Using local TLE file ({int(age / 60)} mins old)"
                log("CACHE", cache_msg)
                cache_valid = True
            else:
                old_tle_msg = (
                    f"TLE file is old ({int(age / 3600)}h). "
                    f"Attempting refresh."
                )
                log("CACHE", old_tle_msg)

        # Fetch fresh data if cache is stale
        if not cache_valid:
            log("API", "Fetching fresh TLEs from CelesTrak...")
            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                r = requests.get(
                    self.celestrak_url, headers=headers, timeout=45
                )

                if r.status_code == 200:
                    lines = r.text.strip().splitlines()
                    log("API", f"CelesTrak success: {len(lines)} lines")

                    # Fetch McCants classified satellites
                    try:
                        log(
                            "API",
                            "Fetching classified TLEs from McCants...",
                        )
                        mccants_r = requests.get(
                            self.mccants_url, headers=headers, timeout=45
                        )
                        mccants_r.raise_for_status()

                        # Extract TLE from zip file
                        zf_data = io.BytesIO(mccants_r.content)
                        with zipfile.ZipFile(zf_data) as z:
                            tle_file_bytes = z.read("classfd.tle")
                            tle_content = tle_file_bytes.decode("utf-8")
                            mccants_lines = tle_content.strip().splitlines()
                            lines.extend(mccants_lines)
                            mccants_msg = (
                                f"McCants success: {len(mccants_lines)} lines"
                            )
                            log("API", mccants_msg)
                    except (
                        requests.RequestException,
                        ValueError,
                        OSError,
                    ) as e:
                        fetch_error = f"McCants fetch failed (continuing): {e}"
                        log("WARN", fetch_error)

                    # Cache combined data
                    with open(self.cache_file, "w", encoding="utf-8") as f:
                        f.write("\n".join(lines))
                    log("API", f"Total TLE lines cached: {len(lines)}")
                elif r.status_code == 403:
                    log("API", "403 Forbidden. Using cache.")
                else:
                    log("API", f"Error {r.status_code}. Using cache.")
            except requests.RequestException as e:
                log("API", f"Network error: {e}. Using cache.")

        # Parse TLE data
        return self._parse_tles(lines)

    def _parse_tles(self, lines: List[str]) -> List[Dict[str, Any]]:
        """Parse TLE lines into satellite objects."""
        ts = load.timescale()
        satellites = []
        i = 0

        while i < len(lines):
            # Handle different TLE formats
            if lines[i].startswith("1 "):
                name = "Unknown"
                l1 = lines[i]
                l2 = lines[i + 1]
                i += 2
            elif i + 1 < len(lines) and lines[i + 1].startswith("1 "):
                name = lines[i].strip()
                l1 = lines[i + 1]
                l2 = lines[i + 2]
                i += 3
            else:
                i += 1
                continue

            try:
                sat = EarthSatellite(l1, l2, name, ts)
                # Extract group identifier from name
                # Special handling: USA satellites are individual,
                # not a constellation
                if (
                    name.startswith("USA ")
                    and len(name.split()) >= 2
                    and name.split()[1].isdigit()
                ):
                    # Individual classified satellite
                    # Use full name as group (each is unique)
                    gid = name
                elif "-" in name:
                    gid = name.split("-")[0]
                else:
                    gid = name.split(" ")[0]
                satellites.append({"sat": sat, "name": name, "group": gid})
            except (ValueError, IndexError, ArithmeticError):
                continue

        log("SYSTEM", f"Loaded {len(satellites)} satellite objects")
        return satellites


class AircraftClient:
    """Fetch aircraft positions from OpenSky Network."""

    def __init__(self):
        self.api_url = CONFIG.get_api_url("opensky")
        self.username = CONFIG.opensky_username
        self.password = CONFIG.opensky_password
        self.cooldown_until = 0

    def fetch_aircraft(self) -> List[Dict[str, Any]]:
        """
        Fetch aircraft positions within search box
        around observatory.

        Returns:
            List of aircraft dicts with 'name', 'lat',
            'lon', 'alt_m' keys
        """
        # Check cooldown
        if time.time() < self.cooldown_until:
            remaining = int(self.cooldown_until - time.time())
            if remaining % 60 == 0:
                cooldown_msg = (
                    f"OpenSky cooldown active. Resuming in {remaining}s..."
                )
                log("API", cooldown_msg)
            return []

        # Build search box
        box = [
            CONFIG.obs_lat - CONFIG.plane_search_box_deg,
            CONFIG.obs_lon - CONFIG.plane_search_box_deg,
            CONFIG.obs_lat + CONFIG.plane_search_box_deg,
            CONFIG.obs_lon + CONFIG.plane_search_box_deg,
        ]

        log("API", "Fetching aircraft from OpenSky...")
        aircraft = []
        auth = (
            (self.username, self.password)
            if (self.username and self.password)
            else None
        )

        try:
            url = (
                f"{self.api_url}/all?"
                f"lamin={box[0]}&lomin={box[1]}&"
                f"lamax={box[2]}&lomax={box[3]}"
            )
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, auth=auth, timeout=10)

            if r.status_code == 200:
                data = r.json()
                if data and data.get("states"):
                    for p in data["states"]:
                        # Try barometric altitude first,
                        # then geometric
                        alt = p[7] if p[7] is not None else p[13]
                        if p[5] and p[6] and alt is not None:
                            aircraft.append(
                                {
                                    "name": p[1].strip(),
                                    "lat": p[6],
                                    "lon": p[5],
                                    "alt_m": alt,
                                }
                            )
                    opensky_msg = (
                        f"OpenSky success: {len(aircraft)} raw "
                        f"aircraft found"
                    )
                    log("API", opensky_msg)
                else:
                    log("API", "OpenSky: No aircraft in range")

            elif r.status_code == 429:
                # Handle rate limiting
                retry_header = r.headers.get(
                    "X-Rate-Limit-Retry-After-Seconds"
                )
                wait_time = int(retry_header) + 5 if retry_header else 300
                rate_msg = f"OpenSky rate limit (429). Waiting {wait_time}s"
                log("API", rate_msg)
                self.cooldown_until = time.time() + wait_time

            else:
                log("API", f"OpenSky error {r.status_code}: {r.text[:50]}")

        except (requests.RequestException, ValueError, KeyError) as e:
            log("API", f"Request error: {e}")

        if not aircraft:
            msg = (
                "OpenSky: fetched 0 aircraft (after filtering "
                "invalid lat/lon/alt)"
            )
            log("API", msg)
        return aircraft


class HorizonClient:
    """Fetch horizon profile from HeyWhatsThat."""

    def __init__(self):
        self.cache_file = CONFIG.horizon_file
        self.panorama_id = CONFIG.panorama_id
        self.resolution = CONFIG.panorama_resolution
        self.api_url = CONFIG.get_api_url("horizon")

    def get_horizon(self) -> Tuple[List[float], List[float], List[float]]:
        """
        Get horizon profile (azimuth, altitude, distance)
        Downloads if not cached.

        Returns:
            Tuple of (azimuth_list, altitude_list,
            distance_list)
        """
        # Download if not cached
        if not os.path.exists(self.cache_file):
            self._download_horizon()

        # Parse cached file
        return self._parse_horizon()

    def _download_horizon(self):
        """Download horizon profile from HeyWhatsThat."""
        log("HORIZON", "Downloading horizon profile...")
        try:
            url = (
                f"{self.api_url}?id={self.panorama_id}&"
                f"resolution={self.resolution}"
            )
            r = requests.get(url, timeout=30)

            if r.status_code == 200:
                with open(self.cache_file, "wb") as f:
                    f.write(r.content)
                log("HORIZON", "Download successful")
            else:
                log("HORIZON", f"Download failed: {r.status_code}")
        except (requests.RequestException, OSError) as e:
            log("HORIZON", f"Download error: {e}")

    def _parse_horizon(self) -> Tuple[List[float], List[float], List[float]]:
        """Parse horizon CSV file."""
        az_list, alt_list, dist_list = [], [], []

        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # Skip header

                for row in reader:
                    if len(row) >= 4:
                        try:
                            az_list.append(float(row[1]))
                            alt_list.append(float(row[2]))
                            dist_list.append(float(row[3]))
                        except ValueError:
                            pass

            if az_list:
                # Sort by azimuth
                zipped = sorted(zip(az_list, alt_list, dist_list))
                az_tuple, alt_tuple, dist_tuple = zip(*zipped)
                log("HORIZON", f"Loaded {len(az_tuple)} horizon points")
                return list(az_tuple), list(alt_tuple), list(dist_tuple)

        except (OSError, ValueError) as e:
            log("HORIZON", f"Parse error: {e}")

        return [], [], []


class GeoDataClient:
    """Fetch geospatial data for world map overlays."""

    def __init__(self):
        self.cache_file = CONFIG.geo_cache_file
        self.world_url = CONFIG.get_api_url("world_geojson")
        self.usa_url = CONFIG.get_api_url("usa_geojson")

    def init_geo_maps(self):
        """Initialize geospatial data cache if not present."""
        if os.path.exists(self.cache_file):
            return

        log("GEO", "Downloading geospatial data...")

        world_data = self._parse_geojson(self.world_url)
        usa_data = self._parse_geojson(self.usa_url)

        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump({"world": world_data, "usa": usa_data}, f)

        log("GEO", "Geospatial data cached")

    def _parse_geojson(self, url: str) -> Dict[str, List]:
        """Parse GeoJSON from URL and convert to 3D \
        coordinates."""
        x: List[Optional[float]] = []
        y: List[Optional[float]] = []
        z: List[Optional[float]] = []

        try:
            data = requests.get(url, timeout=10).json()

            for feature in data.get("features", []):
                geo = feature["geometry"]

                # Handle Polygon and MultiPolygon
                if geo["type"] == "Polygon":
                    polys = [geo["coordinates"]]
                else:
                    polys = geo["coordinates"]

                for poly in polys:
                    for loop in poly:
                        for pt in loop:
                            lat_pt = pt[1]
                            lon_pt = pt[0]
                            cx, cy, cz = self._latlon_to_cartesian(
                                lat_pt, lon_pt
                            )
                            x.append(cx)
                            y.append(cy)
                            z.append(cz)
                        # Add None to separate shapes
                        x.append(None)
                        y.append(None)
                        z.append(None)

        except (requests.RequestException, ValueError, KeyError) as e:
            log("GEO", f"Parse error for {url}: {e}")

        return {"x": x, "y": y, "z": z}

    @staticmethod
    def _latlon_to_cartesian(
        lat: float, lon: float
    ) -> Tuple[float, float, float]:
        """Convert lat/lon to 3D cartesian coordinates.

        Earth radius in km.
        """
        r = 6371  # Earth radius in km
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)

        x = r * math.cos(lat_rad) * math.cos(lon_rad)
        y = r * math.cos(lat_rad) * math.sin(lon_rad)
        z = r * math.sin(lat_rad)

        return x, y, z


# Global client instances
tle_client = TLEClient()
aircraft_client = AircraftClient()
horizon_client = HorizonClient()
geo_client = GeoDataClient()
