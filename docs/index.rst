CASM RFI Sky Monitor Documentation
===================================

Welcome to the CASM RFI Sky Monitor documentation. This project provides real-time tracking and visualization of satellites and aircraft visibility from a ground-based observatory.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   overview
   installation
   configuration
   api/index

Overview
--------

The CASM RFI Sky Monitor is a Flask-based web application that:

- Tracks satellite positions using Two-Line Element (TLE) data
- Monitors aircraft positions via the OpenSky Network API
- Calculates visibility based on observatory horizon profile
- Provides 2D and 3D globe visualizations
- Stores historical snapshots in SQLite database
- Exposes REST API for programmatic access

Key Features
~~~~~~~~~~~~

- **Real-time Data**: Live satellite and aircraft position updates
- **Horizon Masking**: Accounts for local terrain obstructions
- **Historical Tracking**: Snapshot database for temporal analysis
- **Web Interface**: Interactive plots (rectangular and polar views)
- **REST API**: Machine-readable access to position data
- **Flexible Configuration**: YAML-based setup for different observatories

Quick Start
-----------

1. **Installation**::

    git clone <repository>
    cd casm_rfi_sky
    make install

2. **Configuration**: Edit `config.yaml` with your observatory details

3. **Run Development Server**::

    make dev

4. **Access Web Interface**: Open http://localhost:5666

API Documentation
-----------------

See the :doc:`api/index` for complete API reference and module documentation.

Indices and Tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
