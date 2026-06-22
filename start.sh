#!/bin/bash
# Startup script for Dropbear + Python Universal Proxy
# Designed for PaaS environments with dynamic $PORT

set -e  # Exit on error

# Dropbear configuration - use ports >1024 to avoid permission issues
DROPBEAR_PORT=2222
FALLBACK_PORT=3333
DROPBEAR_USER="tunneluser"
DROPBEAR_HOST_KEY_DIR="/etc/dropbear"
DROPBEAR_RSA_KEY="${DROPBEAR_HOST_KEY_DIR}/dropbear_rsa_host_key"
LOG_FILE="/app/logs/dropbear.log"

# Log function with timestamp
log() {
    echo "[$(date -u +'%Y-%m-%d %H:%M:%S')] $*"
}

log "Starting Dropbear SSH server setup"

# Create key directory and set permissions
mkdir -p "${DROPBEAR_HOST_KEY_DIR}" "/app/logs"
chown -R ${DROPBEAR_USER}:${DROPBEAR_USER} "${DROPBEAR_HOST_KEY_DIR}" "/app/logs"

# Generate RSA host key if it doesn't exist
if [ ! -f "${DROPBEAR_RSA_KEY}" ]; then
    log "Generating RSA host key (2048-bit)..."
    dropbearkey -t rsa -f "${DROPBEAR_RSA_KEY}" -s 2048
    chmod 600 "${DROPBEAR_RSA_KEY}"
    chown ${DROPBEAR_USER}:${DROPBEAR_USER} "${DROPBEAR_RSA_KEY}"
else
    log "RSA host key already exists at ${DROPBEAR_RSA_KEY}"
fi

# Function to start Dropbear on a given port
start_dropbear() {
    local port=$1
    log "Attempting to start Dropbear on port ${port}"
    dropbear -F -R -p "${port}" \
        -r "${DROPBEAR_RSA_KEY}" \
        -T 3 \
        -W 3600 \
        -g \
        -j \
        -k \
        -c /bin/false \
        -u ${DROPBEAR_USER} \
        > "${LOG_FILE}" 2>&1 &
    local pid=$!
    sleep 2
    if ss -tulpn 2>/dev/null | grep -q ":${port}"; then
        log "Dropbear is listening on port ${port} (PID ${pid})"
        echo "${port}"
        return 0
    else
        log "Failed to bind on port ${port} (check ${LOG_FILE})"
        kill "${pid}" 2>/dev/null || true
        return 1
    fi
}

# Try primary port, then fallback
PORT_SET=""
if start_dropbear ${DROPBEAR_PORT}; then
    PORT_SET=${DROPBEAR_PORT}
else
    log "Primary port failed. Trying fallback ${FALLBACK_PORT}"
    if start_dropbear ${FALLBACK_PORT}; then
        PORT_SET=${FALLBACK_PORT}
    else
        log "FATAL: Dropbear could not bind to any port. Exiting."
        cat "${LOG_FILE}" 2>/dev/null || echo "No log file available"
        exit 1
    fi
fi

# Export the port so proxy.py can read it
export DROPBEAR_PORT=${PORT_SET}

# Update proxy.py if fallback port was used
if [ "${PORT_SET}" != "${DROPBEAR_PORT}" ]; then
    sed -i "s/TARGET_PORT = 109/TARGET_PORT = ${PORT_SET}/" /app/proxy.py
    log "Updated proxy.py to use port ${PORT_SET}"
fi

log "Dropbear is ready on port ${PORT_SET}. Starting Python proxy on \$PORT..."
exec python3 -u /app/proxy.py
