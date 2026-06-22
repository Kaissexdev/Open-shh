#!/usr/bin/env python3
"""
Universal Payload Proxy for Dropbear SSH tunnel.
Listens on 0.0.0.0:$PORT, detects connection type:
- WebSocket Upgrade: performs HTTP 101 handshake then bridges
- HTTP CONNECT/Proxy: responds with 200 Connection Established
- Raw SSH: direct TCP bridge (no HTTP parsing)
Multi-threaded with thread pool for concurrent connections.
Logs SNI/host from HTTP requests for monitoring.
"""

import socket
import sys
import os
import threading
import select
import re
import logging
from datetime import datetime

# Configure logging to stdout (captured by PaaS logs)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Configuration
LISTEN_PORT = int(os.environ.get('PORT', 8080))  # PaaS provides $PORT
TARGET_HOST = '127.0.0.1'
TARGET_PORT = 109  # Internal Dropbear port
BUFFER_SIZE = 8192
CONNECTION_TIMEOUT = 60  # seconds

# Thread-local storage for connection statistics (optional)
thread_local = threading.local()

def log_connection(src_addr, dst_addr, protocol, sni=None):
    """Structured logging for connection tracking"""
    msg = f"CONN: {src_addr} -> {dst_addr} | PROTO={protocol}"
    if sni:
        msg += f" | SNI={sni}"
    logger.info(msg)

def extract_sni_from_http(data):
    """
    Parse HTTP Host header to extract domain (SNI).
    Returns domain string or None if not found.
    """
    try:
        # Decode only the first few bytes to avoid binary garbage
        text = data[:2048].decode('utf-8', errors='ignore')
        # Look for Host: header (case-insensitive)
        match = re.search(r'Host:\s*([^\r\n]+)', text, re.IGNORECASE)
        if match:
            host = match.group(1).strip()
            # Remove port if present
            if ':' in host:
                host = host.split(':')[0]
            return host
        # Also check for CONNECT method which includes host:port
        match = re.search(r'CONNECT\s+([^\s:]+)', text, re.IGNORECASE)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None

def detect_connection_type(data):
    """
    Detect the type of incoming connection based on initial payload.
    Returns one of: 'websocket', 'http_proxy', 'ssh_direct'
    """
    if not data:
        return 'ssh_direct'  # Empty payload - assume raw SSH

    # Check for WebSocket upgrade headers
    try:
        text = data[:1024].decode('utf-8', errors='ignore').lower()
        if 'upgrade: websocket' in text and 'connection: upgrade' in text:
            return 'websocket'
        # Also handle Sec-WebSocket-Key presence
        if 'sec-websocket-key' in text:
            return 'websocket'
    except Exception:
        pass

    # Check for HTTP CONNECT or other proxy methods
    try:
        text = data[:256].decode('utf-8', errors='ignore')
        if text.startswith(('CONNECT', 'GET', 'POST', 'PUT', 'DELETE', 'HEAD', 'OPTIONS', 'PATCH')):
            # It's an HTTP request - treat as proxy unless it's WebSocket (already caught)
            return 'http_proxy'
    except Exception:
        pass

    # Default: assume raw SSH (starts with SSH banner or binary)
    return 'ssh_direct'

def handle_websocket_handshake(client_sock, data):
    """
    Perform WebSocket HTTP 101 upgrade handshake.
    Returns True if handshake sent successfully.
    """
    try:
        # Parse the original request to echo back proper headers
        # Extract Sec-WebSocket-Key and other required headers
        text = data[:2048].decode('utf-8', errors='ignore')
        key_match = re.search(r'Sec-WebSocket-Key:\s*([^\r\n]+)', text, re.IGNORECASE)
        if not key_match:
            # If no key, send generic upgrade (some clients don't send key)
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Accept: dummy-key-accept\r\n"
                "\r\n"
            )
        else:
            key = key_match.group(1).strip()
            # Compute accept hash as per RFC 6455 (simplified - for real use use hashlib)
            # But many clients accept any 24-char base64; we send a dummy valid one for speed
            # To be fully compliant, uncomment the hashlib lines below
            import hashlib
            import base64
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
    """
    Respond to HTTP CONNECT or generic proxy request with 200 Connection Established.
    Some clients send CONNECT, others send plain HTTP with Host header.
    """
    try:
        # Extract SNI for logging before responding
        sni = extract_sni_from_http(data)
        response = "HTTP/1.1 200 Connection Established\r\n\r\n"
        client_sock.send(response.encode())
        return True, sni
    except Exception as e:
        logger.error(f"HTTP proxy response failed: {e}")
        return False, None

def bridge_connections(src_sock, dst_sock, src_addr, dst_addr, protocol, sni=None):
    """
    Bidirectional data transfer between client and target (Dropbear).
    Uses non-blocking select with timeout for graceful shutdown.
    """
    log_connection(src_addr, dst_addr, protocol, sni)
    # Set sockets to non-blocking for select
    src_sock.setblocking(False)
    dst_sock.setblocking(False)
    
    # Track if we've sent initial data already (for client->server direction)
    # We'll use a simple select loop
    running = True
    src_buf = b''
    dst_buf = b''
    
    # We already read the initial data from client before detection
    # That data is still in the socket buffer? Actually we read it in the main loop.
    # We'll pass the initial data to this function for forwarding.
    # The caller will handle sending the initial data.
    
    # Since we already consumed the initial data in the detect phase, we need to
    # pass it here. We'll modify the bridge function signature to include initial_data.
    # But for cleaner design, we'll handle initial data in the main loop.
    # Actually, we've already read the first chunk - we need to forward it.
    # So we'll re-implement the bridge inside the main loop to avoid double-buffering.
    # Let's restructure: main loop reads first chunk, then passes everything including that chunk.
    
    # For now, we return a closure or re-architect.
    # The clean approach: in the main thread, after detection and handshake,
    # we spawn a new thread that handles the full bridging.
    pass

def handle_client(client_sock, client_addr):
    """
    Main client handler: read initial data, detect type, perform handshake,
    then spawn bridging thread.
    """
    try:
        # Set timeout for initial read
        client_sock.settimeout(5.0)
        # Read the first chunk of data (enough for detection)
        initial_data = client_sock.recv(BUFFER_SIZE)
        if not initial_data:
            client_sock.close()
            return

        # Detect connection type
        conn_type = detect_connection_type(initial_data)
        sni = None
        handshake_ok = True

        # Handle different types
        if conn_type == 'websocket':
            logger.info(f"WebSocket upgrade detected from {client_addr}")
            handshake_ok = handle_websocket_handshake(client_sock, initial_data)
            if not handshake_ok:
                client_sock.close()
                return
            # After handshake, we don't need to forward the initial data
            # because it was the HTTP upgrade request; WebSocket frames follow.
            initial_data_to_forward = b''
            protocol = 'websocket'
        elif conn_type == 'http_proxy':
            logger.info(f"HTTP proxy request from {client_addr}")
            handshake_ok, sni = handle_http_connect(client_sock, initial_data)
            if not handshake_ok:
                client_sock.close()
                return
            # After 200 response, the client will send the actual tunnel data
            initial_data_to_forward = b''
            protocol = 'http_proxy'
        else:  # ssh_direct
            logger.info(f"Raw SSH connection from {client_addr}")
            # No handshake needed; forward the initial data as-is
            initial_data_to_forward = initial_data
            protocol = 'ssh_direct'
            sni = None  # No SNI for raw SSH

        # Now connect to Dropbear
        try:
            target_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            target_sock.settimeout(CONNECTION_TIMEOUT)
            target_sock.connect((TARGET_HOST, TARGET_PORT))
        except Exception as e:
            logger.error(f"Failed to connect to Dropbear at {TARGET_HOST}:{TARGET_PORT}: {e}")
            client_sock.close()
            return

        # Log the established connection
        log_connection(client_addr, f"{TARGET_HOST}:{TARGET_PORT}", protocol, sni)

        # Send any initial_data_to_forward to target
        if initial_data_to_forward:
            try:
                target_sock.send(initial_data_to_forward)
            except Exception as e:
                logger.error(f"Error forwarding initial data: {e}")
                client_sock.close()
                target_sock.close()
                return

        # Now bridge the two sockets bidirectionally using threads
        # We'll create two threads: one for each direction
        def forward(src, dst, direction_name):
            """Forward data from src to dst until EOF or error"""
            try:
                while True:
                    data = src.recv(BUFFER_SIZE)
                    if not data:
                        break
                    dst.send(data)
            except (socket.error, ConnectionResetError, BrokenPipeError) as e:
                # Normal closure
                pass
            except Exception as e:
                logger.debug(f"Bridge {direction_name} error: {e}")
            finally:
                # Closing one end will eventually close the other
                try:
                    src.shutdown(socket.SHUT_RD)
                except:
                    pass
                try:
                    dst.shutdown(socket.SHUT_WR)
                except:
                    pass

        # Start two threads
        t1 = threading.Thread(target=forward, args=(client_sock, target_sock, "client->target"), daemon=True)
        t2 = threading.Thread(target=forward, args=(target_sock, client_sock, "target->client"), daemon=True)
        t1.start()
        t2.start()

        # Wait for both threads to finish (one will die when the other closes)
        t1.join(timeout=CONNECTION_TIMEOUT)
        t2.join(timeout=CONNECTION_TIMEOUT)

    except socket.timeout:
        logger.info(f"Client {client_addr} timeout")
    except Exception as e:
        logger.error(f"Handler error for {client_addr}: {e}")
    finally:
        try:
            client_sock.close()
        except:
            pass

def main():
    """Main listener loop with thread pool"""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(('0.0.0.0', LISTEN_PORT))
    server_sock.listen(100)  # Queue up to 100 pending connections
    
    logger.info(f"Universal proxy listening on 0.0.0.0:{LISTEN_PORT}")
    logger.info(f"Forwarding to Dropbear at {TARGET_HOST}:{TARGET_PORT}")
    logger.info("Detection modes: WebSocket | HTTP Proxy | Raw SSH")
    
    # Thread pool: we'll spawn a new thread per connection (simple and effective)
    # For production with high load, consider using concurrent.futures.ThreadPoolExecutor
    while True:
        try:
            client_sock, client_addr = server_sock.accept()
            logger.debug(f"New connection from {client_addr}")
            # Spawn a handler thread
            handler_thread = threading.Thread(
                target=handle_client,
                args=(client_sock, client_addr),
                daemon=True
            )
            handler_thread.start()
        except KeyboardInterrupt:
            logger.info("Shutting down proxy...")
            break
        except Exception as e:
            logger.error(f"Accept error: {e}")
            continue

    server_sock.close()

if __name__ == '__main__':
    main()
