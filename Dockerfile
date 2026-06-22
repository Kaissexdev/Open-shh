FROM ubuntu:22.04

# Fix interactive prompts
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Install required packages
RUN apt-get update && \
    apt-get install -y \
    openssh-server \
    sudo \
    curl \
    python3 \
    python3-pip \
    net-tools \
    iproute2 \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Configure SSH
RUN mkdir -p /var/run/sshd && \
    echo "Port 2222" >> /etc/ssh/sshd_config && \
    echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config && \
    echo "PermitRootLogin yes" >> /etc/ssh/sshd_config && \
    echo "AllowTcpForwarding yes" >> /etc/ssh/sshd_config && \
    echo "GatewayPorts yes" >> /etc/ssh/sshd_config && \
    echo "PermitTunnel yes" >> /etc/ssh/sshd_config && \
    echo "ClientAliveInterval 60" >> /etc/ssh/sshd_config && \
    echo "ClientAliveCountMax 3" >> /etc/ssh/sshd_config

# Create user
RUN useradd -m -s /bin/bash tunneluser && \
    echo 'tunneluser:ChangeThisPassword123' | chpasswd && \
    usermod -aG sudo tunneluser

# Create working proxy script
RUN echo 'import socket, threading, sys, time\n\
\n\
def forward(src, dst):\n\
    try:\n\
        while True:\n\
            data = src.recv(4096)\n\
            if not data:\n\
                break\n\
            dst.sendall(data)\n\
    except:\n\
        pass\n\
    finally:\n\
        src.close()\n\
        dst.close()\n\
\n\
def handle_client(client_sock):\n\
    try:\n\
        # Read initial request\n\
        request = client_sock.recv(4096)\n\
        \n\
        # Send WebSocket/HTTP upgrade response\n\
        if b"HTTP/" in request:\n\
            response = b"HTTP/1.1 101 Switching Protocols\\r\\n" + \
                      b"Upgrade: websocket\\r\\n" + \
                      b"Connection: Upgrade\\r\\n" + \
                      b"Sec-WebSocket-Accept: dummy\\r\\n\\r\\n"\n\
            client_sock.sendall(response)\n\
        \n\
        # Connect to local SSH\n\
        ssh_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n\
        ssh_sock.settimeout(10)\n\
        ssh_sock.connect(("127.0.0.1", 2222))\n\
        \n\
        # Start bidirectional forwarding\n\
        t1 = threading.Thread(target=forward, args=(client_sock, ssh_sock))\n\
        t2 = threading.Thread(target=forward, args=(ssh_sock, client_sock))\n\
        t1.daemon = True\n\
        t2.daemon = True\n\
        t1.start()\n\
        t2.start()\n\
        t1.join()\n\
        t2.join()\n\
    except Exception as e:\n\
        pass\n\
    finally:\n\
        try:\n\
            client_sock.close()\n\
        except:\n\
            pass\n\
\n\
def main():\n\
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 80\n\
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n\
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n\
    server.bind(("0.0.0.0", port))\n\
    server.listen(100)\n\
    print(f"Proxy listening on port {port}")\n\
    while True:\n\
        client, addr = server.accept()\n\
        t = threading.Thread(target=handle_client, args=(client,))\n\
        t.daemon = True\n\
        t.start()\n\
\n\
if __name__ == "__main__":\n\
    main()' > /proxy.py

# Expose ports
EXPOSE 2222
EXPOSE 80 443 8080 10000

# Start everything
CMD sh -c '\
    LISTEN_PORT=${PORT:-80}; \
    echo "Starting SSH on port 2222..."; \
    /usr/sbin/sshd -D -p 2222 & \
    sleep 5; \
    echo "SSH started. Starting proxy on port $LISTEN_PORT..."; \
    MESSAGE="🚀 <b>SSH Tunnel is LIVE!</b>%0A%0A<b>Host:</b> $(hostname).onrender.com%0A<b>Port:</b> ${LISTEN_PORT}%0A<b>User:</b> tunneluser%0A<b>Pass:</b> ChangeThisPassword123%0A%0A<b>SSH Port:</b> 2222"; \
    curl -s -X POST "https://api.telegram.org/bot8935196204:AAGpPVb7VlZ7qSzU7nmOP95UR4BLr4L-ItA/sendMessage" \
        -d chat_id="6264372980" \
        -d text="${MESSAGE}" \
        -d parse_mode="HTML" || echo "Telegram notification failed"; \
    python3 /proxy.py ${LISTEN_PORT}'
