"""
Background task scheduler for periodic data updates.
Manages TLE updates, aircraft tracking, and database snapshots.
"""

import datetime
import threading
import time
from typing import Any, Dict, List, Optional

from src.api_clients import aircraft_client, geo_client, tle_client
from src.calculations import position_calc
from src.config import CONFIG
from src.database import db
from src.utils import log


class DataState:
    """Thread-safe state management for current data."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tles = []
        self._aircraft = []
        self._stats = {"planes_total": 0, "horizon_points": 0}

    def set_tles(self, tles: List[Dict[str, Any]]):
        """Set satellite TLE data."""
        with self._lock:
            self._tles = tles

    def get_tles(self) -> List[Dict[str, Any]]:
        """Get satellite TLE data."""
        with self._lock:
            return self._tles.copy()

    def set_aircraft(self, aircraft: List[Dict[str, Any]]):
        """Set aircraft data."""
        with self._lock:
            self._aircraft = aircraft
            self._stats["planes_total"] = len(aircraft)

    def get_aircraft(self) -> List[Dict[str, Any]]:
        """Get aircraft data."""
        with self._lock:
            return self._aircraft.copy()

    def get_stats(self) -> Dict[str, int]:
        """Get statistics."""
        with self._lock:
            return self._stats.copy()


class Scheduler:
    """Manages periodic background tasks."""

    def __init__(self, data_state: DataState):
        self.state = data_state
        self.running = False
        # Track manual snapshots for rate limiting
        self.last_forced_snapshot = 0.0
        # Track last aircraft fetch time
        self.last_aircraft_fetch = 0.0

    def run_forever(self):
        """Run the scheduler loop forever."""
        # Initialize
        db.init_db()
        geo_client.init_geo_maps()

        log("SYSTEM", "Starting scheduler...")

        # Initial data fetch
        tles = tle_client.fetch_tles()
        self.state.set_tles(tles)

        aircraft = aircraft_client.fetch_aircraft()
        self.state.set_aircraft(aircraft)

        # Track last fetch times
        last_tle = time.time()
        last_aircraft = time.time()

        # Align next snapshot to clean interval
        now = time.time()
        next_snapshot = (
            int(now) // CONFIG.db_snapshot_interval + 1
        ) * CONFIG.db_snapshot_interval
        next_dt = datetime.datetime.fromtimestamp(next_snapshot)
        next_time = next_dt.strftime("%H:%M:%S")
        log(
            "SYSTEM",
            f"Next snapshot aligned to: {next_time}",
        )

        self.running = True

        # Main loop
        while self.running:
            now = time.time()

            # Update TLEs if needed
            if now - last_tle > CONFIG.tle_fetch_interval:
                tles = tle_client.fetch_tles()
                self.state.set_tles(tles)
                last_tle = now

            # Update aircraft if needed
            if now - last_aircraft > CONFIG.plane_fetch_interval:
                aircraft = aircraft_client.fetch_aircraft()
                self.state.set_aircraft(aircraft)
                last_aircraft = now
                self.last_aircraft_fetch = now

            # Take snapshot if needed
            if now >= next_snapshot:
                self._take_snapshot(scheduled_time=next_snapshot)
                next_snapshot += CONFIG.db_snapshot_interval

            time.sleep(1)

    def _take_snapshot(self, scheduled_time: Optional[float] = None):
        """Take a database snapshot of current visible objects."""
        log("DB", "Taking snapshot...")

        tles = self.state.get_tles()
        aircraft = self.state.get_aircraft()

        objects = position_calc.calculate_visible_objects(tles, aircraft)
        db.save_snapshot(objects, scheduled_time)

    def force_snapshot(self, wait_for_aircraft: bool = True) -> Dict[str, Any]:
        """Force a snapshot with rate limiting.

        Args:
            wait_for_aircraft: If True, wait for fresh
                aircraft data before snapshot

        Returns:
            Dict with status, message, and optional snapshot data
        """
        now = time.time()
        min_interval = 30  # Minimum 30 seconds between forced snapshots

        # Check rate limit
        time_since_last = now - self.last_forced_snapshot
        if time_since_last < min_interval:
            wait_time = int(min_interval - time_since_last)
            return {
                "status": "rate_limited",
                "message": (
                    f"Please wait {wait_time} seconds before "
                    f"taking another snapshot"
                ),
                "wait_seconds": wait_time,
            }

        # Check if we need fresh aircraft data
        if wait_for_aircraft:
            time_since_aircraft = now - self.last_aircraft_fetch
            if time_since_aircraft > CONFIG.plane_fetch_interval:
                log("SNAPSHOT", "Fetching fresh aircraft data...")
                aircraft = aircraft_client.fetch_aircraft()
                self.state.set_aircraft(aircraft)
                self.last_aircraft_fetch = now

        # Take the snapshot
        log("SNAPSHOT", "Manual snapshot requested")
        tles = self.state.get_tles()
        aircraft = self.state.get_aircraft()
        objects = position_calc.calculate_visible_objects(tles, aircraft)

        snapshot_id = db.save_snapshot(objects, scheduled_time=now)
        self.last_forced_snapshot = now

        plane_count = sum(1 for o in objects if o["type"] == "plane")
        sat_count = sum(1 for o in objects if o["type"] == "sat")

        return {
            "status": "success",
            "message": (
                f"Snapshot saved: {sat_count} satellites, "
                f"{plane_count} aircraft"
            ),
            "snapshot_id": snapshot_id,
            "object_count": len(objects),
            "satellite_count": sat_count,
            "aircraft_count": plane_count,
        }

    def stop(self):
        """Stop the scheduler."""
        self.running = False


# Global state and scheduler
state = DataState()
scheduler = Scheduler(state)
