#!/bin/bash
set -e

DROPBEAR_USER="tunneluser"
DROPBEAR_HOST_KEY_DIR="/etc/dropbear"
DROPBEAR_RSA_KEY="${DROPBEAR_HOST_KEY_DIR}/dropbear_rsa_host_key"

log() { echo "[$(date -u +'%Y-%m-%d %H:%M:%S')] $*"; }

mkdir -p "${DROPBEAR_HOST_KEY_DIR}"
chown -R ${DROPBEAR_USER}:${DROPBEAR_USER} "${DROPBEAR_HOST_KEY_DIR}"

if [ ! -f "${DROPBEAR_RSA_KEY}" ]; then
    log "Generating RSA host key..."
    dropbearkey -t rsa -f "${DROPBEAR_RSA_KEY}" -s 2048
    chmod 600 "${DROPBEAR_RSA_KEY}"
    chown ${DROPBEAR_USER}:${DROPBEAR_USER} "${DROPBEAR_RSA_KEY}"
else
    log "RSA host key exists."
fi

log "Starting Python proxy on \$PORT..."
exec python3 -u /app/proxy.py
