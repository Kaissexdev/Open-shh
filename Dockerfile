# syntax=docker/dockerfile:1
FROM alpine:3.19

# Install required packages
RUN apk add --no-cache \
    dropbear \
    openssl \
    python3 \
    py3-pip \
    supervisor

# Create a self-signed certificate for the target SNI host
RUN mkdir -p /etc/tls && \
    openssl req -x509 -newkey rsa:4096 -sha256 -days 36500 -nodes \
        -keyout /etc/tls/privkey.pem \
        -out /etc/tls/fullchain.pem \
        -subj "/CN=applynow.hdfc.bank.in" \
        -addext "subjectAltName = DNS:applynow.hdfc.bank.in"

# Configure Dropbear SSH server
RUN mkdir /etc/dropbear && \
    touch /var/log/dropbear.log && \
    chmod 600 /var/log/dropbear.log
COPY dropbear-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/dropbear-entrypoint.sh

# Install a simple WebSocket‑to‑TCP proxy written in Python
COPY ws_proxy.py /opt/ws_proxy.py

# Supervisor configuration to run Dropbear, stunnel (TLS termination), and the ws_proxy
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose port 443 (TLS+WebSocket) and 22 (Dropbear directly, optional)
EXPOSE 443 22

# Health check endpoint (plain HTTP on port 8081 for platform monitoring)
EXPOSE 8081

# Entrypoint
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]