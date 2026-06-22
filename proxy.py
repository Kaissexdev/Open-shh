#!/usr/bin/env python3
"""
Universal Payload Proxy with Dropbear in inetd mode.
Listens on 0.0.0.0:$PORT, detects connection type:
- WebSocket Upgrade: performs HTTP 101 handshake then bridges to Dropbear subprocess
- HTTP CONNECT/Proxy: responds with 200 Connection Established
- Raw SSH: direct bridge to Dropbear subprocess
"""

import socket
import sys
import os
import threading
import subprocess
import re
import logging
import struct
import hashlib
import base64
import pty
import select

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

LISTEN_PORT = int(os.environ.get('PORT', 8080))
BUFFER_SIZE = 8192
CONNECTION_TIMEOUT = 60

# Path to dropbear binary – we will spawn it with -i (inetd mode)
DROPBEAR_PATH = "/usr/sbin/dropbear"
DROPBEAR_KEY = "/etc/dropbear/dropbear_rsa_host_key"
DROPBEAR_USER = "tunneluser"

def log_connection(src_addr, dst_addr, protocol, sni=None):
    msg = f"CONN: {src_addr} -> {dst_addr} | PROTO={protocol}"
    if sni:
        msg += f" | SNI={sni}"
    logger.info(msg)

def extract_sni_from_http(data):
    try:
        text = data[:2048].decode('utf-8', errors='ignore')
        match = re.search(r'Host:\s*([^\r\n]+)', text, re.IGNORECASE)
        if match:
            host = match.group(1).strip()
            if ':' in host:
                host = host.split(':')[0]
            return host
        match = re.search(r'CONNECT\s+([^\s:]+)', text, re.IGNORECASE)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None

def detect_connection_type(data):
    if not data:
        return 'ssh_direct'
    try:
        text = data[:1024].decode('utf-8', errors='ignore').lower()
        if 'upgrade: websocket' in text and 'connection: upgrade' in text:
            return 'websocket'
        if 'sec-websocket-key' in text:
            return 'websocket'
    except Exception:
        pass
    try:
        text = data[:256].decode('utf-8', errors='ignore')
        if text.startswith(('CONNECT', 'GET', 'POST', 'PUT', 'DELETE', 'HEAD', 'OPTIONS', 'PATCH')):
            return 'http_proxy'
    except Exception:
        pass
    return 'ssh_direct'

def handle_websocket_handshake(client_sock, data):
    try:
        text = data[:2048].decode('utf-8', errors='ignore')
        key_match = re.search(r'Sec-WebSocket-Key:\s*([^\r\n]+)', text, re.IGNORECASE)
        if not key_match:
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Accept: dummy-key-accept\r\n"
                "\r\n"
            )
        else:
            key = key_match.group(1).strip()
            magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
            accept = base64.b64encode(hashlib.sha1((key + magic).encode()).digest()).decode()
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "\r\n"
            )
        client_sock.send(response.encode())
        return True
    except Exception as e:
        logger.error(f"WebSocket handshake failed: {e}")
        return False

def handle_http_connect(client_sock, data):
    try:
        sni = extract_sni_from_http(data)
        response = "HTTP/1.1 200 Connection Established\r\nContent-Length: 0\r\n\r\n"
        client_sock.send(response.encode())
        return True, sni
    except Exception as e:
        logger.error(f"HTTP proxy response failed: {e}")
        return False, None

def spawn_dropbear_inetd(client_sock):
    """
    Spawn dropbear in inetd mode (-i) and connect client_sock to its stdio.
    dropbear -i reads from stdin/writes to stdout, handling SSH on that single connection.
    """
    try:
        # Create a pipe to communicate with dropbear
        # We use pty to make dropbear happy (it expects a tty in inetd mode)
        master_fd, slave_fd = pty.openpty()
        
        # Spawn dropbear with -i (inetd mode) and -r for host key
        proc = subprocess.Popen(
            [
                DROPBEAR_PATH,
                "-i",           # inetd mode
                "-r", DROPBEAR_KEY,
                "-c", "/bin/false",
                "-u", DROPBEAR_USER,
                "-T", "3",
                "-W", "3600",
            ],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            preexec_fn=os.setsid
        )
        os.close(slave_fd)
        
        logger.debug(f"Spawned dropbear (PID {proc.pid}) for client")
        
        # Bridge client socket <-> master_fd (dropbear stdio)
        # Use select to forward data both ways
        client_sock.setblocking(False)
        master_fd = os.fdopen(master_fd, 'rb+', buffering=0)
        master_fd.fileno()  # ensure it's a real fd
        
        # We need to use raw file descriptor for select
        master_fileno = master_fd.fileno()
        client_fileno = client_sock.fileno()
        
        while proc.poll() is None:
            rlist, _, _ = select.select([client_fileno, master_fileno], [], [], 0.1)
            if client_fileno in rlist:
                try:
                    data = client_sock.recv(BUFFER_SIZE)
                    if not data:
                        break
                    os.write(master_fileno, data)
                except:
                    break
            if master_fileno in rlist:
                try:
                    data = os.read(master_fileno, BUFFER_SIZE)
                    if not data:
                        break
                    client_sock.send(data)
                except:
                    break
        # Cleanup
        proc.terminate()
        proc.wait()
    except Exception as e:
        logger.error(f"Dropbear inetd error: {e}")
    finally:
        try:
            client_sock.close()
        except:
            pass

def handle_client(client_sock, client_addr):
    try:
        client_sock.settimeout(5.0)
        initial_data = client_sock.recv(BUFFER_SIZE)
        if not initial_data:
            client_sock.close()
            return

        conn_type = detect_connection_type(initial_data)
        sni = None
        handshake_ok = True

        if conn_type == 'websocket':
            logger.info(f"WebSocket upgrade from {client_addr}")
            handshake_ok = handle_websocket_handshake(client_sock, initial_data)
            if not handshake_ok:
                client_sock.close()
                return
            protocol = 'websocket'
            # After handshake, any data is WebSocket frames – we need to parse them.
            # For simplicity, we drop the initial data (handshake) and bridge raw.
            # But WebSocket framing requires unmasking – this is a complex bridge.
            # For a production solution, we would use a proper WebSocket library.
            # However, our proxy is designed for VPN apps that expect a raw TCP tunnel
            # after the WebSocket handshake (like DarkTunnel).
            # So we just spawn dropbear and bridge the raw socket.
            # Note: This skips WebSocket masking for simplicity.
            spawn_dropbear_inetd(client_sock)
            return
        elif conn_type == 'http_proxy':
            logger.info(f"HTTP proxy from {client_addr}")
            handshake_ok, sni = handle_http_connect(client_sock, initial_data)
            if not handshake_ok:
                client_sock.close()
                return
            protocol = 'http_proxy'
            # After CONNECT, spawn dropbear and bridge
            spawn_dropbear_inetd(client_sock)
            return
        else:  # ssh_direct
            logger.info(f"Raw SSH from {client_addr}")
            protocol = 'ssh_direct'
            # Send initial data to dropbear and spawn it
            # We need to pass initial data to dropbear's stdin
            # Spawn dropbear inetd and write initial data
            try:
                master_fd, slave_fd = pty.openpty()
                proc = subprocess.Popen(
                    [DROPBEAR_PATH, "-i", "-r", DROPBEAR_KEY, "-c", "/bin/false", "-u", DROPBEAR_USER],
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    preexec_fn=os.setsid
                )
                os.close(slave_fd)
                os.write(master_fd, initial_data)
                # Now bridge
                client_sock.setblocking(False)
                master_fileno = master_fd
                client_fileno = client_sock.fileno()
                while proc.poll() is None:
                    rlist, _, _ = select.select([client_fileno, master_fileno], [], [], 0.1)
                    if client_fileno in rlist:
                        data = client_sock.recv(BUFFER_SIZE)
                        if not data:
                            break
                        os.write(master_fileno, data)
                    if master_fileno in rlist:
                        data = os.read(master_fileno, BUFFER_SIZE)
                        if not data:
                            break
                        client_sock.send(data)
                proc.terminate()
            except Exception as e:
                logger.error(f"Dropbear spawn error: {e}")
            finally:
                client_sock.close()
            return

    except Exception as e:
        logger.error(f"Handler error: {e}", exc_info=True)
    finally:
        try:
            client_sock.close()
        except:
            pass

def main():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(('0.0.0.0', LISTEN_PORT))
    server_sock.listen(100)
    
    logger.info(f"Universal proxy listening on 0.0.0.0:{LISTEN_PORT}")
    logger.info("Dropbear running in inetd mode (spawned per connection)")
    
    while True:
        try:
            client_sock, client_addr = server_sock.accept()
            logger.debug(f"New connection from {client_addr}")
            t = threading.Thread(target=handle_client, args=(client_sock, client_addr), daemon=True)
            t.start()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Accept error: {e}")
    server_sock.close()

if __name__ == '__main__':
    main()
