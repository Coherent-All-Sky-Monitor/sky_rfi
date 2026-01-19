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
        self._aircraft_rate_limit_until = 0.0
        self._last_tle_fetch = 0.0
        self._last_aircraft_fetch = 0.0
        self._last_computation = 0.0
        self._next_snapshot = 0.0
        self._last_forced_snapshot = 0.0

    def set_tles(self, tles: List[Dict[str, Any]]):
        """Set satellite TLE data."""
        with self._lock:
            self._tles = tles
            self._last_tle_fetch = time.time()
        self._save_timestamps_to_file()

    def get_tles(self) -> List[Dict[str, Any]]:
        """Get satellite TLE data."""
        with self._lock:
            return self._tles.copy()

    def set_aircraft(self, aircraft: List[Dict[str, Any]]):
        """Set aircraft data."""
        with self._lock:
            self._aircraft = aircraft
            self._stats["planes_total"] = len(aircraft)
            self._last_aircraft_fetch = time.time()
        self._save_timestamps_to_file()

    def get_aircraft(self) -> List[Dict[str, Any]]:
        """Get aircraft data."""
        with self._lock:
            return self._aircraft.copy()

    def get_stats(self) -> Dict[str, int]:
        """Get statistics."""
        with self._lock:
            return self._stats.copy()

    def set_aircraft_rate_limit(self, until_timestamp: float):
        """Set aircraft API rate limit end time."""
        with self._lock:
            self._aircraft_rate_limit_until = until_timestamp

    def get_aircraft_rate_limit(self) -> float:
        """Get aircraft API rate limit end time (0 if not rate limited)."""
        with self._lock:
            return self._aircraft_rate_limit_until

    def set_last_computation(self, timestamp: float):
        """Set last computation timestamp."""
        with self._lock:
            self._last_computation = timestamp
        self._save_timestamps_to_file()

    def set_last_forced_snapshot(self, timestamp: float):
        """Set last forced snapshot timestamp."""
        with self._lock:
            self._last_forced_snapshot = timestamp
        self._save_timestamps_to_file()

    def set_next_snapshot(self, timestamp: float):
        """Set next scheduled snapshot timestamp."""
        with self._lock:
            self._next_snapshot = timestamp
        self._save_timestamps_to_file()

    def get_next_snapshot(self) -> float:
        """Get next scheduled snapshot timestamp."""
        self._load_timestamps_from_file()
        with self._lock:
            return self._next_snapshot

    def get_last_forced_snapshot(self) -> float:
        """Get last forced snapshot timestamp."""
        self._load_timestamps_from_file()
        with self._lock:
            return self._last_forced_snapshot

    def get_timestamps(self) -> Dict[str, float]:
        """Get all tracked timestamps."""
        # Try to load from file first (for multi-worker sync)
        self._load_timestamps_from_file()
        with self._lock:
            return {
                "last_tle_fetch": self._last_tle_fetch,
                "last_aircraft_fetch": self._last_aircraft_fetch,
                "last_computation": self._last_computation,
            }

    def _save_timestamps_to_file(self):
        """Save timestamps to file for multi-worker sync."""
        import json
        import os

        timestamp_file = "data/.timestamps.json"
        os.makedirs("data", exist_ok=True)
        try:
            with open(timestamp_file, "w") as f:
                json.dump(
                    {
                        "last_tle_fetch": self._last_tle_fetch,
                        "last_aircraft_fetch": self._last_aircraft_fetch,
                        "last_computation": self._last_computation,
                        "next_snapshot": self._next_snapshot,
                        "last_forced_snapshot": self._last_forced_snapshot,
                    },
                    f,
                )
        except Exception:
            pass  # Ignore errors

    def _load_timestamps_from_file(self):
        """Load timestamps from file for multi-worker sync."""
        import json

        timestamp_file = "data/.timestamps.json"
        try:
            with open(timestamp_file, "r") as f:
                data = json.load(f)
                with self._lock:
                    self._last_tle_fetch = data.get("last_tle_fetch", 0.0)
                    self._last_aircraft_fetch = data.get(
                        "last_aircraft_fetch", 0.0
                    )
                    self._last_computation = data.get("last_computation", 0.0)
                    self._next_snapshot = data.get("next_snapshot", 0.0)
                    self._last_forced_snapshot = data.get(
                        "last_forced_snapshot", 0.0
                    )
        except (FileNotFoundError, json.JSONDecodeError):
            pass  # File doesn't exist yet or is invalid


class Scheduler:
    """Manages periodic background tasks."""

    def __init__(self, data_state: DataState):
        self.state = data_state
        self.running = False
        # Track manual snapshots for rate limiting (persisted via DataState)
        # Track last aircraft fetch time
        self.last_aircraft_fetch = 0.0
        # Track next scheduled snapshot time
        self.next_snapshot = 0.0

    def run_forever(self):
        """Run the scheduler loop forever."""
        # Initialize
        db.init_db()
        geo_client.init_geo_maps()

        log("SYSTEM", "Starting scheduler...")

        # Fetch initial TLE data
        log("SYSTEM", "Fetching initial TLE data...")
        tles = tle_client.fetch_tles()
        self.state.set_tles(tles)
        last_tle = time.time()

        # Fetch initial aircraft data
        log("SYSTEM", "Fetching initial aircraft data...")
        aircraft = aircraft_client.fetch_aircraft()
        self.state.set_aircraft(aircraft)
        self.state.set_aircraft_rate_limit(aircraft_client.cooldown_until)

        # Align next snapshot to clean interval
        now = time.time()
        self.next_snapshot = (
            int(now) // CONFIG.db_snapshot_interval + 1
        ) * CONFIG.db_snapshot_interval
        self.state.set_next_snapshot(self.next_snapshot)
        next_dt = datetime.datetime.fromtimestamp(self.next_snapshot)
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

            # Take snapshot if needed
            if now >= self.next_snapshot:
                # Fetch fresh aircraft data for snapshot
                aircraft = aircraft_client.fetch_aircraft()
                self.state.set_aircraft(aircraft)
                self.state.set_aircraft_rate_limit(
                    aircraft_client.cooldown_until
                )

                # Check if we have valid data and not rate limited
                tles = self.state.get_tles()
                rate_limit_until = self.state.get_aircraft_rate_limit()

                # Skip snapshot if:
                # 1. No satellite data
                # 2. No aircraft data
                # 3. Aircraft API is rate limited
                if not tles:
                    log("DB", "Skipping snapshot: No satellite data available")
                elif not aircraft:
                    log("DB", "Skipping snapshot: No aircraft data available")
                elif time.time() < rate_limit_until:
                    remaining = int(rate_limit_until - time.time())
                    log(
                        "DB",
                        (
                            "Skipping snapshot: Aircraft API rate limited "
                            f"({remaining}s remaining)"
                        ),
                    )
                else:
                    self._take_snapshot(scheduled_time=self.next_snapshot)

                self.next_snapshot += CONFIG.db_snapshot_interval
                self.state.set_next_snapshot(self.next_snapshot)
                next_dt = datetime.datetime.fromtimestamp(self.next_snapshot)
                next_time = next_dt.strftime("%H:%M:%S")
                log(
                    "SYSTEM",
                    f"Next snapshot scheduled for: {next_time}",
                )

            time.sleep(1)

    def _take_snapshot(self, scheduled_time: Optional[float] = None):
        """Take a database snapshot of current visible objects."""
        log("DB", "Taking snapshot...")

        tles = self.state.get_tles()
        aircraft = self.state.get_aircraft()

        objects = position_calc.calculate_visible_objects(tles, aircraft)
        self.state.set_last_computation(time.time())
        db.save_snapshot(objects, scheduled_time)

    def get_status(self) -> dict:
        """Get scheduler status for UI display.

        Returns:
            Dict with scheduler status and timestamps
        """
        now = time.time()
        min_interval = 30  # Must match force_snapshot cooldown
        last_forced = self.state.get_last_forced_snapshot()
        force_available_at = last_forced + min_interval
        timestamps = self.state.get_timestamps()
        next_snapshot = self.state.get_next_snapshot()

        return {
            "next_snapshot_at": (
                next_snapshot if next_snapshot > 0 else self.next_snapshot
            ),
            "force_snapshot_available_at": (
                force_available_at if force_available_at > now else 0
            ),
            "last_tle_fetch": timestamps["last_tle_fetch"],
            "last_aircraft_fetch": timestamps["last_aircraft_fetch"],
            "last_computation": timestamps["last_computation"],
        }

    def force_snapshot(self, wait_for_aircraft: bool = True) -> Dict[str, Any]:
        """Force a snapshot with rate limiting.

        Args:
            wait_for_aircraft: If True, fetch fresh aircraft data before
                snapshot

        Returns:
            Dict with status, message, and optional snapshot data
        """
        now = time.time()
        min_interval = 30  # Minimum 30 seconds between forced snapshots

        # Check rate limit
        time_since_last = now - self.state.get_last_forced_snapshot()
        if time_since_last < min_interval:
            wait_seconds = int(min_interval - time_since_last)
            return {
                "status": "rate_limited",
                "message": (
                    "Snapshot rate limited. Please wait " f"{wait_seconds}s."
                ),
                "wait_seconds": wait_seconds,
            }

        # Fetch fresh aircraft data if requested
        if wait_for_aircraft:
            log("DB", "Fetching fresh aircraft data for manual snapshot...")
            aircraft = aircraft_client.fetch_aircraft()
            self.state.set_aircraft(aircraft)
            self.state.set_aircraft_rate_limit(aircraft_client.cooldown_until)

            # Check if aircraft fetch was rate limited
            if time.time() < aircraft_client.cooldown_until:
                remaining = int(aircraft_client.cooldown_until - time.time())
                return {
                    "status": "error",
                    "message": (
                        "Aircraft API is rate limited. Wait " f"{remaining}s."
                    ),
                    "wait_seconds": remaining,
                }

        # Take the snapshot
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
        # Ensure TLEs are available even when this route runs on a
        # non-scheduler worker
        if not tles:
            log("DB", "No TLEs in state; loading from cache...")
            try:
                tles = tle_client.fetch_tles()
                self.state.set_tles(tles)
                log("DB", f"Loaded {len(tles)} satellites for snapshot")
            except Exception as e:
                log("WARN", f"Failed to load TLEs for snapshot: {e}")
                tles = []
        aircraft = self.state.get_aircraft()
        objects = position_calc.calculate_visible_objects(tles, aircraft)
        self.state.set_last_computation(time.time())

        snapshot_id = db.save_snapshot(objects, scheduled_time=now)
        self.state.set_last_forced_snapshot(now)

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
