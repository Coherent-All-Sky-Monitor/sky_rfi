Installation
=============

Requirements
------------

- Python 3.8 or higher
- pip or uv package manager
- Virtual environment (recommended)

Quick Install
-------------

Using pip::

    git clone <repository>
    cd casm_rfi_sky
    python3 -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    pip install -r requirements.txt

Using make (recommended)::

    make install

Using uv (faster)::

    make install-uv

Verify Installation
~~~~~~~~~~~~~~~~~~~

Test that all dependencies are installed::

    make test

Development Setup
-----------------

For development with linting and formatting tools::

    pip install isort black flake8 pylint
    pip install sphinx sphinx-rtd-theme sphinx-autodoc-typehints

Running the Application
-----------------------

Development Mode
~~~~~~~~~~~~~~~~

With auto-reload and debug enabled::

    make dev

The server will be available at ``http://localhost:5666``

Production Mode
~~~~~~~~~~~~~~~

Using Gunicorn::

    make prod

Configure host and port::

    make prod HOST=0.0.0.0 PORT=8000

Service Installation (Linux only)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Install as a systemd service::

    sudo make service-install

View logs::

    make service-logs
