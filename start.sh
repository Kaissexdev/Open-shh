#!/bin/bash
# Startup script for Dropbear + Python Universal Proxy
# Designed for PaaS environments with dynamic $PORT

set -e  # Exit on error

# Dropbear configuration
DROPBEAR_PORT=109
DROPBEAR_USER="tunneluser"
DROPBEAR_PASSWORD="aroma26"
DROPBEAR_HOST_KEY_DIR="/etc/dropbear"
DROPBEAR_RSA_KEY="${DROPBEAR_HOST_KEY_DIR}/dropbear_rsa_host_key"

# Log function with timestamp
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

log "Starting Dropbear SSH server on internal port ${DROPBEAR_PORT}"

# Generate RSA host key if it doesn't exist
if [ ! -f "${DROPBEAR_RSA_KEY}" ]; then
    log "Generating Dropbear RSA host key..."
    dropbearkey -t rsa -f "${DROPBEAR_RSA_KEY}" -s 2048
    # Set proper ownership (though we run as tunneluser, key file must be readable)
    chmod 600 "${DROPBEAR_RSA_KEY}"
else
    log "RSA host key already exists at ${DROPBEAR_RSA_KEY}"
fi

# Start Dropbear in background
# Options:
#   -F : Don't fork into background (we want it to stay, but we'll background it manually)
#   -R : Don't allow root logins (we don't have root anyway)
#   -p : Port to listen on
#   -r : Host key file
#   -b : Banner (optional)
#   -T : Maximum authentication attempts (increase security)
#   -W : Idle session timeout (seconds)
dropbear -F -R -p ${DROPBEAR_PORT} \
    -r "${DROPBEAR_RSA_KEY}" \
    -T 3 \
    -W 3600 \
    -s \
    -g \
    -j \
    -k \
    -m \
    -c /bin/false \
    -u ${DROPBEAR_USER} \
    > /dev/null 2>&1 &

# Capture Dropbear PID for potential monitoring
DROPBEAR_PID=$!
log "Dropbear started with PID ${DROPBEAR_PID}"

# Wait a moment for Dropbear to fully initialize
sleep 2

# Verify Dropbear is listening
if netstat -tulpn 2>/dev/null | grep -q ":${DROPBEAR_PORT}"; then
    log "Dropbear is listening on port ${DROPBEAR_PORT}"
else
    log "WARNING: Dropbear may not be listening correctly. Checking..."
    # Alternative check using ss
    if ss -tulpn 2>/dev/null | grep -q ":${DROPBEAR_PORT}"; then
        log "Dropbear confirmed listening (via ss)"
    else
        log "ERROR: Dropbear failed to bind to port ${DROPBEAR_PORT}. Check logs."
        # Don't exit - let the proxy run anyway, but log the error
    fi
fi

# Start the Python universal proxy in foreground
log "Starting Python universal proxy on port \${PORT} (external)"
log "Proxy will forward to Dropbear on 127.0.0.1:${DROPBEAR_PORT}"

# The proxy reads PORT from environment and listens on 0.0.0.0:$PORT
exec python3 /app/proxy.py
