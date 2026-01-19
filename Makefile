# Makefile for CASM RFI Sky Monitor

# Configuration
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
FLASK := $(VENV)/bin/flask
GUNICORN := $(VENV)/bin/gunicorn
UV := $(shell command -v uv 2> /dev/null)

# Read server configuration from config.yaml
DEV_HOST := $(shell $(PYTHON) -c "import yaml; f=open('config.yaml'); d=yaml.safe_load(f) or {}; print(d.get('server', {}).get('dev_host', '127.0.0.1'))" 2>/dev/null || echo '127.0.0.1')
DEV_PORT := $(shell $(PYTHON) -c "import yaml; f=open('config.yaml'); d=yaml.safe_load(f) or {}; print(d.get('server', {}).get('dev_port', 5000))" 2>/dev/null || echo '5000')
PROD_HOST := $(shell $(PYTHON) -c "import yaml; f=open('config.yaml'); d=yaml.safe_load(f) or {}; print(d.get('server', {}).get('prod_host', '127.0.0.1'))" 2>/dev/null || echo '127.0.0.1')
PROD_PORT := $(shell $(PYTHON) -c "import yaml; f=open('config.yaml'); d=yaml.safe_load(f) or {}; print(d.get('server', {}).get('prod_port', 5000))" 2>/dev/null || echo '5000')
PROD_WORKERS := $(shell $(PYTHON) -c "import yaml; f=open('config.yaml'); d=yaml.safe_load(f) or {}; print(d.get('server', {}).get('prod_workers', 4))" 2>/dev/null || echo '4')

# Server configuration (from config.yaml, override with: make prod HOST=0.0.0.0 PORT=8000)
HOST ?= $(PROD_HOST)
PORT ?= $(PROD_PORT)
WORKERS ?= $(PROD_WORKERS)

# Colors for terminal output
COLOR_RESET := \033[0m
COLOR_GREEN := \033[32m
COLOR_YELLOW := \033[33m
COLOR_BLUE := \033[34m

.PHONY: help install install-uv dev prod clean test status check-compat

help:
	@echo "$(COLOR_BLUE)CASM sky RFI Monitor - Available Commands$(COLOR_RESET)"
	@echo ""
	@echo "  $(COLOR_GREEN)make install$(COLOR_RESET)         - Create virtual environment and install dependencies"
	@echo "  $(COLOR_GREEN)make install-uv$(COLOR_RESET)      - Install dependencies using uv (faster)"
	@echo "  $(COLOR_GREEN)make check-compat$(COLOR_RESET)    - Check Python 3.8+ compatibility"
	@echo "  $(COLOR_GREEN)make service-install$(COLOR_RESET) - Install as Linux systemd service (requires sudo)"
	@echo "  $(COLOR_GREEN)make service-uninstall$(COLOR_RESET) - Uninstall systemd service (requires sudo)"
	@echo "  $(COLOR_GREEN)make service-log$(COLOR_RESET)     - View service logs"
	@echo "  $(COLOR_GREEN)make dev$(COLOR_RESET)             - Run server in development mode (Flask debug)"
	@echo "  $(COLOR_GREEN)make prod$(COLOR_RESET)            - Run server in production mode (gunicorn)"
	@echo "  $(COLOR_GREEN)make test$(COLOR_RESET)            - Test installation and dependencies"
	@echo "  $(COLOR_GREEN)make status$(COLOR_RESET)          - Check installation status"
	@echo "  $(COLOR_GREEN)make clean$(COLOR_RESET)           - Remove virtual environment and cache files"
	@echo "  $(COLOR_GREEN)make clean-data$(COLOR_RESET)      - Remove cached data files (keeps database)"
	@echo ""
	@echo "$(COLOR_YELLOW)Configuration:$(COLOR_RESET)"
	@echo "  Edit config.yaml for permanent settings, or override at command line:"
	@echo ""
	@echo "  HOST (default from config.yaml)   - Server bind address"
	@echo "  PORT (default from config.yaml)   - Server port"
	@echo "  WORKERS (default from config.yaml) - Gunicorn worker processes"
	@echo ""
	@echo "$(COLOR_YELLOW)Examples:$(COLOR_RESET)"
	@echo "  make dev                          # Uses config.yaml server settings"
	@echo "  make dev HOST=0.0.0.0 PORT=8080   # Override config.yaml"
	@echo "  make prod                         # Production with config settings"
	@echo ""

# Linux systemd service management
service-install:
	@echo "$(COLOR_YELLOW)Installing systemd service...$(COLOR_RESET)"
	@sudo ./scripts/service_manager.sh install

service-uninstall:
	@sudo ./scripts/service_manager.sh uninstall

service-start:
	@sudo ./scripts/service_manager.sh start

service-stop:
	@sudo ./scripts/service_manager.sh stop

service-restart:
	@sudo ./scripts/service_manager.sh restart

service-status:
	@./scripts/service_manager.sh status

service-logs:
	@./scripts/service_manager.sh logs

# Create virtual environment and install dependencies
install: $(VENV)/bin/activate

$(VENV)/bin/activate: requirements.txt
	@echo "$(COLOR_YELLOW)Creating virtual environment...$(COLOR_RESET)"
	python3 -m venv $(VENV)
	@echo "$(COLOR_YELLOW)Upgrading pip and installing build tools...$(COLOR_RESET)"
	$(PIP) install --upgrade pip setuptools wheel
	@echo "$(COLOR_YELLOW)Installing dependencies...$(COLOR_RESET)"
	$(PIP) install -r requirements.txt
	@echo "$(COLOR_GREEN)Installation complete!$(COLOR_RESET)"
	@echo ""
	@echo "Run '$(COLOR_BLUE)make dev$(COLOR_RESET)' to start the development server"
	@echo "Run '$(COLOR_BLUE)make prod$(COLOR_RESET)' to start the production server"

# Run in development mode (Flask debug server)
dev: $(VENV)/bin/activate
	@echo "$(COLOR_YELLOW)Starting development server...$(COLOR_RESET)"
	@echo "$(COLOR_BLUE)URL: http://$(DEV_HOST):$(DEV_PORT)$(COLOR_RESET)"
	@echo "Press Ctrl+C to stop"
	@echo ""
	FLASK_RUN_HOST=$(DEV_HOST) FLASK_RUN_PORT=$(DEV_PORT) $(PYTHON) -m src.app

# Run in production mode using gunicorn (Unix/Linux/macOS only)
prod: $(VENV)/bin/activate
	@echo "$(COLOR_YELLOW)Starting production server (gunicorn)...$(COLOR_RESET)"
	@echo "$(COLOR_BLUE)URL: http://$(HOST):$(PORT)$(COLOR_RESET)"
	@echo "Workers: $(WORKERS)"
	@echo "Press Ctrl+C to stop"
	@echo ""
	$(GUNICORN) -w $(WORKERS) -b $(HOST):$(PORT) 'src.app:app'

# Test installation
test: $(VENV)/bin/activate
	@echo "$(COLOR_YELLOW)Testing installation...$(COLOR_RESET)"
	@$(PYTHON) -c "import yaml; print('[OK] PyYAML installed')"
	@$(PYTHON) -c "import flask; print('[OK] Flask installed')"
	@$(PYTHON) -c "import skyfield; print('[OK] Skyfield installed')"
	@$(PYTHON) -c "import plotly; print('[OK] Plotly installed')"
	@$(PYTHON) -c "import numpy; print('[OK] NumPy installed')"
	@$(PYTHON) -c "import requests; print('[OK] Requests installed')"
	@echo "$(COLOR_GREEN)All dependencies installed correctly!$(COLOR_RESET)"
	@echo ""
	@echo "Testing configuration file..."
	@$(PYTHON) -c "from src.config import CONFIG; print(f'[OK] Config loaded: Observatory = {CONFIG.obs_name}')"
	@echo "$(COLOR_GREEN)Configuration OK!$(COLOR_RESET)"

# Check installation status
status:
	@echo "$(COLOR_BLUE)Installation Status:$(COLOR_RESET)"
	@if [ -d "$(VENV)" ]; then \
		echo "  Virtual environment: $(COLOR_GREEN)[OK] Installed$(COLOR_RESET)"; \
	else \
		echo "  Virtual environment: $(COLOR_YELLOW)[MISSING] Not found (run 'make install')$(COLOR_RESET)"; \
	fi
	@if [ -f "config.yaml" ]; then \
		echo "  Configuration file:  $(COLOR_GREEN)[OK] Found$(COLOR_RESET)"; \
	else \
		echo "  Configuration file:  $(COLOR_YELLOW)[MISSING] Missing$(COLOR_RESET)"; \
	fi
	@if [ -d "data" ]; then \
		echo "  Data directory:      $(COLOR_GREEN)[OK] Found$(COLOR_RESET)"; \
	else \
		echo "  Data directory:      $(COLOR_YELLOW)[MISSING] Missing$(COLOR_RESET)"; \
	fi
	@if [ -d "templates" ]; then \
		echo "  Templates:           $(COLOR_GREEN)[OK] Found$(COLOR_RESET)"; \
	else \
		echo "  Templates:           $(COLOR_YELLOW)[MISSING] Missing$(COLOR_RESET)"; \
	fi
	@if [ -d "static" ]; then \
		echo "  Static files:        $(COLOR_GREEN)[OK] Found$(COLOR_RESET)"; \
	else \
		echo "  Static files:        $(COLOR_YELLOW)[MISSING] Missing$(COLOR_RESET)"; \
	fi

# Remove virtual environment and cache files
clean:
	@echo "$(COLOR_YELLOW)Removing virtual environment...$(COLOR_RESET)"
	rm -rf $(VENV)
	@echo "$(COLOR_YELLOW)Removing Python cache files...$(COLOR_RESET)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@echo "$(COLOR_GREEN)Clean complete!$(COLOR_RESET)"
	@echo "Run '$(COLOR_BLUE)make install$(COLOR_RESET)' to reinstall"

# Remove cached data files (preserves database)
clean-data:
	@echo "$(COLOR_YELLOW)Removing cache files...$(COLOR_RESET)"
	rm -f data/*.txt data/*.json 2>/dev/null || true
	@echo "$(COLOR_GREEN)Cache files removed!$(COLOR_RESET)"
install-uv:
	@if [ -z "$(UV)" ]; then \
		echo "$(COLOR_RED)Error: uv not found. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh$(COLOR_RESET)"; \
		exit 1; \
	fi
	@echo "$(COLOR_YELLOW)Installing dependencies with uv...$(COLOR_RESET)"
	@mkdir -p data
	@uv venv $(VENV)
	@uv pip install --python $(VENV) -r requirements.txt
	@echo "$(COLOR_GREEN)Installation complete!$(COLOR_RESET)"
	@echo ""
	@echo "Run '$(COLOR_BLUE)make dev$(COLOR_RESET)' to start the development server"
	@echo "Run '$(COLOR_BLUE)make prod$(COLOR_RESET)' to start the production server"

# Check Python 3.8+ compatibility
check-compat:
	@echo "$(COLOR_BLUE)Checking Python 3.8+ compatibility...$(COLOR_RESET)"
	@echo ""
	@if [ -z "$(UV)" ]; then \
		echo "$(COLOR_YELLOW)Note: Install uv for better compatibility checking:$(COLOR_RESET)"; \
		echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		echo ""; \
	fi
	@echo "$(COLOR_YELLOW)Current Python version:$(COLOR_RESET)"
	@python3 --version
	@echo ""
	@echo "$(COLOR_YELLOW)Checking dependency compatibility...$(COLOR_RESET)"
	@if [ -n "$(UV)" ]; then \
		uv pip compile pyproject.toml --python-version 3.8 --quiet 2>&1 > /tmp/uv-compat-3.8.txt && \
		echo "$(COLOR_GREEN)[OK] Compatible with Python 3.8$(COLOR_RESET)" || \
		echo "$(COLOR_RED)[FAIL] Issues with Python 3.8$(COLOR_RESET)"; \
		uv pip compile pyproject.toml --python-version 3.9 --quiet 2>&1 > /tmp/uv-compat-3.9.txt && \
		echo "$(COLOR_GREEN)[OK] Compatible with Python 3.9$(COLOR_RESET)" || \
		echo "$(COLOR_RED)[FAIL] Issues with Python 3.9$(COLOR_RESET)"; \
		uv pip compile pyproject.toml --python-version 3.10 --quiet 2>&1 > /tmp/uv-compat-3.10.txt && \
		echo "$(COLOR_GREEN)[OK] Compatible with Python 3.10$(COLOR_RESET)" || \
		echo "$(COLOR_RED)[FAIL] Issues with Python 3.10$(COLOR_RESET)"; \
		uv pip compile pyproject.toml --python-version 3.11 --quiet 2>&1 > /tmp/uv-compat-3.11.txt && \
		echo "$(COLOR_GREEN)[OK] Compatible with Python 3.11$(COLOR_RESET)" || \
		echo "$(COLOR_RED)[FAIL] Issues with Python 3.11$(COLOR_RESET)"; \
		uv pip compile pyproject.toml --python-version 3.12 --quiet 2>&1 > /tmp/uv-compat-3.12.txt && \
		echo "$(COLOR_GREEN)[OK] Compatible with Python 3.12$(COLOR_RESET)" || \
		echo "$(COLOR_RED)[FAIL] Issues with Python 3.12$(COLOR_RESET)"; \
		uv pip compile pyproject.toml --python-version 3.13 --quiet 2>&1 > /tmp/uv-compat-3.13.txt && \
		echo "$(COLOR_GREEN)[OK] Compatible with Python 3.13$(COLOR_RESET)" || \
		echo "$(COLOR_RED)[FAIL] Issues with Python 3.13$(COLOR_RESET)"; \
	else \
		echo "$(COLOR_YELLOW)Install uv for automated compatibility checking$(COLOR_RESET)"; \
	fi
	@echo ""
	@echo "$(COLOR_BLUE)Dependency versions:$(COLOR_RESET)"
	@echo "  Flask: >=3.0.0 (requires Python 3.8+)"
	@echo "  NumPy: >=1.20.0 for Python <3.9, >=1.26.0 for Python >=3.9"
	@echo "  Skyfield: >=1.46 (compatible with Python 3.8+)"
	@echo "  Plotly: >=5.18.0 (compatible with Python 3.8+)"
	@echo ""
# Default target
.DEFAULT_GOAL := help
