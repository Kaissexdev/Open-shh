FROM ubuntu:latest

# Fix for Exit Code 1: Stops apt-get from asking interactive questions during installation
ENV DEBIAN_FRONTEND=noninteractive

# Install OpenSSH server, sudo, curl, tzdata, and python3 for the proxy script
RUN apt-get update && \
    apt-get install -y openssh-server sudo curl tzdata python3 && \
    mkdir -p /var/run/sshd && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Configure SSH for tunneling (Moving SSH to port 2222 internally)
RUN sed -i 's/#AllowTcpForwarding yes/AllowTcpForwarding yes/' /etc/ssh/sshd_config && \
    sed -i 's/#GatewayPorts no/GatewayPorts yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PermitTunnel no/PermitTunnel yes/' /etc/ssh/sshd_config && \
    echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config && \
    echo "Port 2222" >> /etc/ssh/sshd_config

# Create the tunnel user
RUN useradd -m -s /bin/bash tunneluser && \
    echo 'tunneluser:ChangeThisPassword123' | chpasswd && \
    usermod -aG sudo tunneluser

# Create a Python WebSocket-to-SSH Proxy Script
# This accepts ANY HTTP payload, returns a 101 connection success, and connects to SSH
RUN echo 'import socket, threading, sys\n\
def handle(client):\n\
    try:\n\
        req = client.recv(8192)\n\
        if b"HTTP/" in req:\n\
            client.sendall(b"HTTP/1.1 101 Switching Protocols\\r\\nUpgrade: websocket\\r\\nConnection: Upgrade\\r\\n\\r\\n")\n\
        ssh = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n\
        ssh.connect(("127.0.0.1", 2222))\n\
        def fwd(s, d):\n\
            try:\n\
                while True:\n\
                    data = s.recv(8192)\n\
                    if not data: break\n\
                    d.sendall(data)\n\
            except: pass\n\
            finally:\n\
                s.close()\n\
                d.close()\n\
        threading.Thread(target=fwd, args=(client, ssh)).start()\n\
        threading.Thread(target=fwd, args=(ssh, client)).start()\n\
    except: pass\n\
s = socket.socket()\n\
s.bind(("0.0.0.0", int(sys.argv[1])))\n\
s.listen(100)\n\
while True:\n\
    c, _ = s.accept()\n\
    threading.Thread(target=handle, args=(c,)).start()' > /proxy.py

EXPOSE 2222
EXPOSE 80 443 8080

# Start SSH internally on 2222, send Telegram alert, and run Python proxy on external PORT
CMD sh -c 'LISTEN_PORT=${PORT:-80}; \
    /usr/sbin/sshd -D -p 2222 & \
    MESSAGE="🚀 <b>BLAC Tunnel SSH Node is Live!</b>%0A%0A<b>Username:</b> tunneluser%0A<b>Password:</b> ChangeThisPassword123%0A<b>Proxy Port:</b> ${LISTEN_PORT}%0A%0A<i>Note: Proxy is running and will accept any payload!</i>"; \
    curl -s -X POST "https://api.telegram.org/bot8935196204:AAGpPVb7VlZ7qSzU7nmOP95UR4BLr4L-ItA/sendMessage" \
        -d chat_id="6264372980" \
        -d text="${MESSAGE}" \
        -d parse_mode="HTML"; \
    python3 /proxy.py ${LISTEN_PORT}'
    
