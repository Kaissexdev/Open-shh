FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Kolkata
ENV PORT=10000

ARG ROOT_PASSWORD=""

# Install tools, SSH, and a lightweight web server
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      openssh-server \
      wget curl git nano vim sudo htop \
      net-tools iputils-ping software-properties-common \
      python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Setup SSH
RUN echo "root:${ROOT_PASSWORD}" | chpasswd \
    && mkdir -p /var/run/sshd \
    && sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config \
    && sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config

# Create a simple web server script
RUN echo '#!/usr/bin/env python3\n\
import http.server\n\
import socketserver\n\
import os\n\
\n\
PORT = int(os.environ.get("PORT", 10000))\n\
Handler = http.server.SimpleHTTPRequestHandler\n\
\n\
with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:\n\
    print(f"Serving at port {PORT}")\n\
    httpd.serve_forever()' > /usr/local/bin/web-server.py && chmod +x /usr/local/bin/web-server.py

# Set hostname and bash prompt
RUN echo "VPS-Server" > /etc/hostname
RUN echo 'export PS1="root@VPS:\\w# "' >> /root/.bashrc

EXPOSE 22 10000

# Start SSH and web server
CMD ["sh", "-c", "/usr/sbin/sshd && python3 /usr/local/bin/web-server.py"]
