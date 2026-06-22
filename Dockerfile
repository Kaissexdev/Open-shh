FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Kolkata
ENV PORT=5000

# Set a default password, can be overridden via environment variable
ENV ROOT_PASSWORD=root123

# Install tools, SSH, and a lightweight web server
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      openssh-server \
      wget curl git nano vim sudo htop \
      net-tools iputils-ping software-properties-common \
      python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Setup SSH on port 22
RUN echo "root:${ROOT_PASSWORD}" | chpasswd \
    && mkdir -p /var/run/sshd \
    && sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config \
    && sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config \
    && sed -i 's/#Port 22/Port 22/' /etc/ssh/sshd_config

# Create working directories
RUN mkdir -p /workspace /data /logs /var/www/html

# Create a simple web server script on port 5000
RUN echo '#!/usr/bin/env python3\n\
import http.server\n\
import socketserver\n\
import os\n\
\n\
PORT = int(os.environ.get("PORT", 5000))\n\
Handler = http.server.SimpleHTTPRequestHandler\n\
\n\
os.chdir("/var/www/html")\n\
\n\
with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:\n\
    print(f"Serving web interface at port {PORT}")\n\
    print(f"SSH server running on port 22")\n\
    print(f"Connect via: ssh root@open-shh.onrender.com -p 22")\n\
    print(f"Password: root123 (change after login)")\n\
    httpd.serve_forever()' > /usr/local/bin/web-server.py && chmod +x /usr/local/bin/web-server.py

# Create HTML page
RUN echo '<!DOCTYPE html>\n\
<html>\n\
<head><title>VPS Server</title></head>\n\
<body>\n\
<h1>Welcome to Your VPS Server</h1>\n\
<p>SSH Server is running on port 22</p>\n\
<p>Connect using: <code>ssh root@open-shh.onrender.com -p 22</code></p>\n\
<p>Default Password: <strong>root123</strong></p>\n\
<p>Status: <strong>Online</strong></p>\n\
</body>\n\
</html>' > /var/www/html/index.html

# Set hostname and bash prompt
RUN echo "VPS-Server" > /etc/hostname
RUN echo 'export PS1="root@VPS:\\w# "' >> /root/.bashrc && \
    echo 'alias ll="ls -alF"' >> /root/.bashrc && \
    echo 'alias la="ls -A"' >> /root/.bashrc && \
    echo 'alias l="ls -CF"' >> /root/.bashrc

EXPOSE 22 5000

# Start SSH and web server
CMD ["sh", "-c", "/usr/sbin/sshd && python3 /usr/local/bin/web-server.py"]
