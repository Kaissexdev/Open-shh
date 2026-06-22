FROM ubuntu:latest

# Fix for Exit Code 1: Stops apt-get from asking interactive questions during installation
ENV DEBIAN_FRONTEND=noninteractive

# Install OpenSSH server, sudo, and curl, then clean up cache to make image lighter
RUN apt-get update && \
    apt-get install -y openssh-server sudo curl tzdata && \
    mkdir -p /var/run/sshd && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Configure SSH for tunneling
RUN sed -i 's/#AllowTcpForwarding yes/AllowTcpForwarding yes/' /etc/ssh/sshd_config && \
    sed -i 's/#GatewayPorts no/GatewayPorts yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PermitTunnel no/PermitTunnel yes/' /etc/ssh/sshd_config && \
    echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config

# Create the tunnel user
RUN useradd -m -s /bin/bash tunneluser && \
    echo 'tunneluser:ChangeThisPassword123' | chpasswd && \
    usermod -aG sudo tunneluser

EXPOSE 22

# Execute the Telegram alert with hardcoded credentials and start the SSH server inline
CMD sh -c 'LISTEN_PORT=${PORT:-22}; \
    MESSAGE="🚀 <b>BLAC Tunnel SSH Node is Live!</b>%0A%0A<b>Username:</b> tunneluser%0A<b>Password:</b> ChangeThisPassword123%0A<b>Internal Port:</b> ${LISTEN_PORT}%0A%0A<i>Note: Check your Railway TCP settings for the external connection Port and Domain.</i>"; \
    curl -s -X POST "https://api.telegram.org/bot8935196204:AAGpPVb7VlZ7qSzU7nmOP95UR4BLr4L-ItA/sendMessage" \
        -d chat_id="6264372980" \
        -d text="${MESSAGE}" \
        -d parse_mode="HTML"; \
    exec /usr/sbin/sshd -D -p ${LISTEN_PORT}'
    
