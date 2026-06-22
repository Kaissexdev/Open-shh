# Use Alpine for minimal footprint (~5MB base)
FROM alpine:latest

# Install required packages: dropbear (SSH server), python3, bash, and build dependencies for key generation
RUN apk add --no-cache \
    dropbear \
    python3 \
    bash \
    openssh-keygen \
    && ln -sf python3 /usr/bin/python

# Create a dedicated user with no shell access (security)
RUN adduser -D -s /bin/false tunneluser && \
    echo "tunneluser:aroma26" | chpasswd

# Create directory for Dropbear host keys and logs with proper permissions
RUN mkdir -p /etc/dropbear /app/logs && \
    chown tunneluser:tunneluser /etc/dropbear /app/logs && \
    chmod 755 /app/logs

# Copy application files
COPY proxy.py /app/proxy.py
COPY start.sh /app/start.sh

# Set executable permissions
RUN chmod +x /app/start.sh && \
    chmod 644 /app/proxy.py

# Switch to non-root user for runtime
USER tunneluser
WORKDIR /app

# Expose the internal Dropbear port (not used by PaaS, but for clarity)
EXPOSE 109

# The start script will run Python proxy in foreground; Dropbear runs in background
CMD ["/app/start.sh"]
