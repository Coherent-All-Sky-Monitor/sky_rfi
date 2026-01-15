# Installation

## Requirements

- Python 3.8 or higher
- pip or uv package manager
- Virtual environment (recommended)

## Quick Install

### Using pip

```bash
git clone <repository>
cd casm_rfi_sky
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Using make (recommended)

```bash
make install
```

### Using uv (faster)

```bash
make install-uv
```

## Verify Installation

Test that all dependencies are installed:

```bash
make test
```

## Development Setup

For development with linting and formatting tools:

```bash
pip install isort black flake8 pylint
```

## Running the Application

### Development Mode

With auto-reload and debug enabled:

```bash
make dev
```

The server will be available at `http://localhost:5666`

### Production Mode

Using Gunicorn:

```bash
make prod
```

Configure host and port:

```bash
make prod HOST=0.0.0.0 PORT=8000
```

### Service Installation (Linux only)

Install as a systemd service:

```bash
sudo make service-install
```

View logs:

```bash
make service-logs
```
