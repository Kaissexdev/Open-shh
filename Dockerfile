# syntax=docker/dockerfile:1
FROM alpine:3.19

RUN apk add --no-cache \
    dropbear \
    openssl \
    python3 \
    py3-pip \
    supervisor \
    stunnel

# Self‑signed certificate for SNI spoofing
RUN mkdir -p /etc/tls && \
    openssl req -x509 -newkey rsa:4096 -sha256 -days 36500 -nodes \
        -keyout /etc/tls/privkey.pem \
        -out /etc/tls/fullchain.pem \
        -subj "/CN=applynow.hdfc.bank.in" \
        -addext "subjectAltName = DNS:applynow.hdfc.bank.in"

# Dropbear directory (use -p to avoid collision)
RUN mkdir -p /etc/dropbear && \
    touch /var/log/dropbear.log && \
    chmod 600 /var/log/dropbear.log

# Entrypoint for Dropbear key generation & start
COPY dropbear-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/dropbear-entrypoint.sh

# WebSocket‑to‑TCP proxy
COPY ws_proxy.py /opt/ws_proxy.py

# Supervisor configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# stunnel TLS termination configuration
COPY stunnel.conf /etc/stunnel/stunnel.conf

EXPOSE 443 22 8081

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
