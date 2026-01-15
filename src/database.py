"""
Database operations for Sky RFI Monitor.
Handles SQLite database initialization, queries, and snapshots.
"""

import sqlite3
import time
from typing import Any, Dict, List, Optional

from src.config import CONFIG
from src.utils import format_timestamp, log


class Database:
    """Handles all database operations."""

    def __init__(self):
        self.db_name = CONFIG.db_name

    def init_db(self):
        """Initialize database schema with optimizations."""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()

        # Enable optimizations
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA journal_mode = WAL")
        c.execute("PRAGMA synchronous = NORMAL")

        # Create snapshots table
        c.execute(
            """CREATE TABLE IF NOT EXISTS snapshots
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      timestamp REAL,
                      readable_time TEXT)"""
        )

        # Create objects table
        c.execute(
            """CREATE TABLE IF NOT EXISTS objects
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      snapshot_id INTEGER,
                      name TEXT,
                      type TEXT,
                      group_id TEXT,
                      az_deg REAL,
                      alt_deg REAL,
                      dist_m REAL,
                      x_km REAL,
                      y_km REAL,
                      z_km REAL,
                      FOREIGN KEY(snapshot_id) REFERENCES
                      snapshots(id) ON DELETE CASCADE)"""
        )

        # Check if 3D position columns exist, add if missing
        c.execute("PRAGMA table_info(objects)")
        cols = [r[1] for r in c.fetchall()]
        if "x_km" not in cols:
            try:
                c.execute("ALTER TABLE objects ADD COLUMN x_km REAL")
                c.execute("ALTER TABLE objects ADD COLUMN y_km REAL")
                c.execute("ALTER TABLE objects ADD COLUMN z_km REAL")
                log("DB", "Added 3D position columns to objects table")
            except sqlite3.Error as e:
                log("DB", f"Column addition failed (may already exist): {e}")

        conn.commit()
        conn.close()
        log("DB", "Database initialized")

    def save_snapshot(
        self,
        objects: List[Dict[str, Any]],
        scheduled_time: Optional[float] = None,
    ) -> Optional[int]:
        """
        Save a snapshot of visible objects to the database.

        Args:
            objects: List of object dictionaries
            scheduled_time: Optional specific timestamp for the snapshot

        Returns:
            Snapshot ID of the saved snapshot, or None if no objects
        """
        if not objects:
            log("DB", "No visible objects. Skipping snapshot.")
            return None

        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("BEGIN TRANSACTION")

        try:
            # Create snapshot record
            now = scheduled_time if scheduled_time else time.time()
            readable = format_timestamp(now)
            insert_sql = (
                "INSERT INTO snapshots "
                "(timestamp, readable_time) VALUES (?, ?)"
            )
            c.execute(insert_sql, (now, readable))
            snapshot_id = c.lastrowid

            # Insert objects
            db_rows = [
                (
                    snapshot_id,
                    o["name"],
                    o["type"],
                    o["group"],
                    o["az"],
                    o["alt"],
                    o["dist"],
                    o["x"],
                    o["y"],
                    o["z"],
                )
                for o in objects
            ]
            insert_objects_sql = (
                "INSERT INTO objects "
                "(snapshot_id, name, type, group_id, "
                "az_deg, alt_deg, dist_m, x_km, y_km, z_km) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)"
            )
            c.executemany(insert_objects_sql, db_rows)

            # Cleanup old snapshots
            cutoff = now - (CONFIG.retention_days * 86400)
            c.execute("DELETE FROM snapshots WHERE timestamp < ?", (cutoff,))

            conn.commit()
            snapshot_msg = (
                f"Snapshot #{snapshot_id} saved with {len(objects)} objects"
            )
            log("DB", snapshot_msg)
            return snapshot_id

        except sqlite3.Error as e:
            log("DB", f"Snapshot write failed: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    def get_snapshot(self, snapshot_id: int) -> List[Dict[str, Any]]:
        """
        Retrieve objects from a specific snapshot.

        Args:
            snapshot_id: ID of the snapshot

        Returns:
            List of object dictionaries
        """
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM objects WHERE snapshot_id=?", (snapshot_id,))
        rows = c.fetchall()
        conn.close()

        return [
            {
                "name": r["name"],
                "type": r["type"],
                "group": r["group_id"],
                "az": r["az_deg"],
                "alt": r["alt_deg"],
                "dist": r["dist_m"],
                "x": r["x_km"],
                "y": r["y_km"],
                "z": r["z_km"],
            }
            for r in rows
        ]

    def get_all_snapshots(self) -> List[Dict[str, Any]]:
        """
        Get list of all snapshots with metadata.

        Returns:
            List of snapshot dictionaries
        """
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        select_sql = (
            "SELECT id, timestamp, readable_time FROM snapshots "
            "ORDER BY id ASC"
        )
        c.execute(select_sql)
        rows = c.fetchall()
        conn.close()

        return [dict(r) for r in rows]


# Global database instance
db = Database()
