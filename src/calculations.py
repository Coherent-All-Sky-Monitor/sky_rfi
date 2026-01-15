"""
Position calculations and visibility determination.
Handles satellite and aircraft position calculations relative to observer.
"""

from typing import Any, Dict, List

import numpy as np
from skyfield.api import load, wgs84
from skyfield.framelib import itrs

from src.api_clients import horizon_client
from src.config import CONFIG
from src.utils import log


class PositionCalculator:
    """Calculate positions and visibility of satellites and aircraft."""

    def __init__(self):
        self.ts = load.timescale()
        self.observer = wgs84.latlon(
            CONFIG.obs_lat, CONFIG.obs_lon, elevation_m=CONFIG.obs_alt
        )

    def calculate_visible_objects(
        self, satellites: List[Dict[str, Any]], aircraft: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Calculate visibility of all objects from observer.

        Args:
            satellites: List of satellite dicts with 'sat',
                'name', 'group'
            aircraft: List of aircraft dicts with 'name',
                'lat', 'lon', 'alt_m'

        Returns:
            List of visible object dictionaries with position data
        """
        t_now = self.ts.now()
        h_az, h_alt, h_dist = horizon_client.get_horizon()
        # Wrap horizon profile for azimuth interpolation
        # across 0/360
        if len(h_az) >= 2:
            h_az = [h_az[-1] - 360] + list(h_az) + [h_az[0] + 360]
            h_alt = [h_alt[-1]] + list(h_alt) + [h_alt[0]]
            h_dist = [h_dist[-1]] + list(h_dist) + [h_dist[0]]

        # Fallback if horizon not available
        if not h_az:
            h_az, h_alt, h_dist = [0, 360], [0, 0], [1e9, 1e9]

        results = []

        # Process satellites
        for item in satellites:
            try:
                sat = item["sat"]
                geo = (sat - self.observer).at(t_now)
                alt, az, dist = geo.altaz()

                # Only consider objects above -5 degrees
                if alt.degrees > -5:
                    h_mask = np.interp(az.degrees, h_az, h_alt)
                    # Satellite visible if above horizon
                    if alt.degrees > h_mask:
                        # Get Earth-fixed (ITRS) position
                        # for 3D globe
                        pos_itrs = sat.at(t_now).frame_xyz(itrs).km
                        results.append(
                            {
                                "name": item["name"],
                                "type": "sat",
                                "group": item["group"],
                                "az": az.degrees,
                                "alt": alt.degrees,
                                "dist": dist.m,
                                "x": pos_itrs[0],
                                "y": pos_itrs[1],
                                "z": pos_itrs[2],
                            }
                        )
            except (ValueError, IndexError, ArithmeticError):
                continue

        # Process aircraft
        visible_planes = 0
        aircraft_msg = (
            f"Aircraft raw count: {len(aircraft)} | "
            f"Horizon points: {len(h_az)}"
        )
        log("MATH", aircraft_msg)
        for p in aircraft:
            try:
                loc = wgs84.latlon(p["lat"], p["lon"], elevation_m=p["alt_m"])
                geo = (loc - self.observer).at(t_now)
                alt, az, dist = geo.altaz()

                h_mask = np.interp(az.degrees, h_az, h_alt)
                h_block_dist = np.interp(az.degrees, h_az, h_dist)

                # Aircraft visibility: allow if above
                # horizon (with tolerance) OR closer than
                # horizon obstruction distance
                if alt.degrees > -5 and (
                    alt.degrees > (h_mask - 0.5) or dist.m < h_block_dist
                ):
                    # Get Earth-fixed (ITRS) position
                    # for 3D globe
                    pos_itrs = loc.at(t_now).frame_xyz(itrs).km
                    results.append(
                        {
                            "name": p["name"],
                            "type": "plane",
                            "group": "Aircraft",
                            "az": az.degrees,
                            "alt": alt.degrees,
                            "dist": dist.m,
                            "x": pos_itrs[0],
                            "y": pos_itrs[1],
                            "z": pos_itrs[2],
                        }
                    )
                    visible_planes += 1
            except (ValueError, IndexError, ArithmeticError) as e:
                plane_err = (
                    f"Aircraft calc error for {p.get('name', '?')}: {e}"
                )
                log("MATH", plane_err)

        vis_msg = (
            f"Calculated visibility: {visible_planes} aircraft, "
            f"{len(results) - visible_planes} satellites"
        )
        log("MATH", vis_msg)
        return results


# Global calculator instance
position_calc = PositionCalculator()
