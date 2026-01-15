API Reference
==============

Core Modules
------------

.. toctree::
   :maxdepth: 2

   generated/src

REST API Endpoints
------------------

Public Endpoints
~~~~~~~~~~~~~~~~

These endpoints do not require authentication.

**GET /api/public/latest**
   Get the latest visible objects (satellites and aircraft).

   Response::

       {
         "2026-01-14 21:30:00": {
           "airplanes": {
             "CALLSIGN": {"alt": 45.2, "az": 120.5, "distance": 10000}
           },
           "satellites": {
             "Starlink": {
               "constellation_name": "Starlink",
               "list": {
                 "STARLINK-XXXX": {"alt": 30.1, "az": 200.3}
               }
             }
           }
         }
       }

**GET /api/public/snapshots**
   Get list of available snapshot IDs and timestamps.

**GET /api/public/snapshot/<int:snapshot_id>**
   Get data from a specific snapshot.

Protected Endpoints
~~~~~~~~~~~~~~~~~~~

These endpoints require an API token in the ``X-API-Token`` header.

**GET /api/live**
   Get current live data with statistics and visualization traces.

   Header::

       X-API-Token: YOUR_API_TOKEN

**GET /api/snapshot/<int:snapshot_id>**
   Get snapshot formatted for visualization traces.

**GET /api/history**
   Get all snapshots with metadata.

**POST /api/force_snapshot**
   Trigger an immediate snapshot.

   Request::

       {
         "wait_for_aircraft": true
       }

Getting an API Token
~~~~~~~~~~~~~~~~~~~~

The API token is displayed in the application logs on startup::

    API token: abcd1234... (PID 12345)

Set ``X-API-Token`` header to this value for protected endpoints.
