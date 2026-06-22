FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Kolkata

ARG ROOT_PASSWORD="root"

# Install minimal tools and tzdata
RUN apt-get update && \
    apt-get install -y --no-install-recommends apt-utils ca-certificates gnupg2 curl wget lsb-release tzdata && \
    ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime && \
    dpkg-reconfigure --frontend noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*

# Install common utilities, SSH, and software-properties-common
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      openssh-server \
      wget \
      curl \
      git \
      nano \
      vim \
      sudo \
      htop \
      net-tools \
      iputils-ping \
      software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Python 3.12
RUN add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get update && \
    apt-get install -y --no-install-recommends python3.12 python3.12-venv python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Make python3 point to python3.12
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

# Install additional tools for VPS-like experience
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      gcc \
      make \
      tmux \
      screen \
      unzip \
      zip \
      tar \
      rsync \
      nginx \
      docker.io \
    && rm -rf /var/lib/apt/lists/*

# Setup SSH
RUN echo "root:${ROOT_PASSWORD}" | chpasswd \
    && mkdir -p /var/run/sshd \
    && sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config \
    && sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config \
    && sed -i 's/#Port 22/Port 22/' /etc/ssh/sshd_config

# Setup bash profile
RUN echo 'export PS1="root@VPS:\\w# "' >> /root/.bashrc && \
    echo 'alias ll="ls -alF"' >> /root/.bashrc && \
    echo 'alias la="ls -A"' >> /root/.bashrc && \
    echo 'alias l="ls -CF"' >> /root/.bashrc

# Create a non-root user (optional)
RUN useradd -m -s /bin/bash user && \
    echo "user:${ROOT_PASSWORD}" | chpasswd && \
    usermod -aG sudo user

# Set hostname
RUN echo "VPS-Server" > /etc/hostname

# Create working directories
RUN mkdir -p /workspace /data /logs

EXPOSE 22

# Start SSH server
CMD ["sh", "-c", "/usr/sbin/sshd -D"]
