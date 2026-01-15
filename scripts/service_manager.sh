#!/bin/bash

# Service Manager Script for CASM sky RFI Monitor
# Handles creation, installation, and management of systemd service

SERVICE_NAME="casm-rfi-sky"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
USER=$(whoami)
GROUP=$(id -gn)
WORKDIR=$(pwd)
VENV_PYTHON="${WORKDIR}/venv/bin/python"
GUNICORN_BIN="${WORKDIR}/venv/bin/gunicorn"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Helper function for logging
log() {
    echo -e "${GREEN}[CASM Service]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[CASM Service]${NC} $1"
}

error() {
    echo -e "${RED}[CASM Service]${NC} $1"
}

# Check if running as root (needed for system installs)
check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "Please run with sudo"
        exit 1
    fi
}

# Generate systemd service file
generate_service_file() {
    # Read config for port/host
    if [ -f "config.yaml" ]; then
        # Quick python parsing to get prod_port and prod_host
        HOST=$($VENV_PYTHON -c "import yaml; print(yaml.safe_load(open('config.yaml')).get('server', {}).get('prod_host', '0.0.0.0'))")
        PORT=$($VENV_PYTHON -c "import yaml; print(yaml.safe_load(open('config.yaml')).get('server', {}).get('prod_port', 5000))")
        WORKERS=$($VENV_PYTHON -c "import yaml; print(yaml.safe_load(open('config.yaml')).get('server', {}).get('prod_workers', 4))")
    else
        HOST="0.0.0.0"
        PORT="5000"
        WORKERS="4"
    fi

    log "Generating service file configuration..."
    log "User: $USER"
    log "Dir:  $WORKDIR"
    log "Bind: $HOST:$PORT"

    cat <<EOF > ${SERVICE_NAME}.service.tmp
[Unit]
Description=CASM RFI Sky Monitor
After=network.target

[Service]
User=$USER
Group=$GROUP
WorkingDirectory=$WORKDIR
Environment="PATH=${WORKDIR}/venv/bin"
ExecStart=${GUNICORN_BIN} --workers ${WORKERS} --bind ${HOST}:${PORT} 'src.app:app'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
}

# Install the service
install_service() {
    check_root
    
    # We need to know the ACTUAL user who owns the files, not root
    # So if sudo is used, we might need to adjust USER variable if it picked up root
    # But usually we want the service to run as the user who owns the files.
    # The script should be called like 'sudo ./scripts/service_manager.sh install <real_user>' or detected.
    
    REAL_USER=${SUDO_USER:-$USER}
    REAL_GROUP=$(id -gn $REAL_USER)
    
    # Regenerate content with REAL_USER if we are root
    USER=$REAL_USER
    GROUP=$REAL_GROUP
    
    generate_service_file
    
    log "Installing ${SERVICE_NAME}.service to systemd..."
    mv ${SERVICE_NAME}.service.tmp $SERVICE_FILE
    
    log "Reloading systemd daemon..."
    systemctl daemon-reload
    
    log "Enabling service to start on boot..."
    systemctl enable $SERVICE_NAME
    
    log "Starting service..."
    systemctl start $SERVICE_NAME
    
    log "Service installed and started!"
    systemctl status $SERVICE_NAME --no-pager
}

# Uninstall service
uninstall_service() {
    check_root
    log "Stopping service..."
    systemctl stop $SERVICE_NAME
    
    log "Disabling service..."
    systemctl disable $SERVICE_NAME
    
    log "Removing service file..."
    rm $SERVICE_FILE
    
    log "Reloading systemd..."
    systemctl daemon-reload
    
    log "Uninstall complete."
}

# Usage menu
case "$1" in
    install)
        install_service
        ;;
    uninstall)
        uninstall_service
        ;;
    start)
        sudo systemctl start $SERVICE_NAME
        ;;
    stop)
        sudo systemctl stop $SERVICE_NAME
        ;;
    restart)
        sudo systemctl restart $SERVICE_NAME
        ;;
    status)
        systemctl status $SERVICE_NAME
        ;;
    logs)
        journalctl -u $SERVICE_NAME -f
        ;;
    *)
        echo "Usage: $0 {install|uninstall|start|stop|restart|status|logs}"
        exit 1
        ;;
esac
