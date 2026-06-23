   #!/usr/bin/env python3
import asyncio
import hashlib
import base64
import struct
import os
import subprocess

HOST, PORT = '0.0.0.0', 8080
SSH_HOST, SSH_PORT = '127.0.0.1', 22
MAGIC = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

# ------------------------------------------------------------
# Health‑check server (port 8081) – serves SSH connection info
# ------------------------------------------------------------
async def handle_health(reader, writer):
    # Dynamically read Dropbear host key fingerprints (only once)
    fingerprints = {}
    for keyfile in ['dropbear_rsa_host_key', 'dropbear_ecdsa_host_key', 'dropbear_ed25519_host_key']:
        path = f'/etc/dropbear/{keyfile}'
        if os.path.exists(path):
            try:
                proc = subprocess.run(['dropbearkey', '-y', '-f', path],
                                      capture_output=True, text=True)
                for line in proc.stdout.splitlines():
                    if 'Fingerprint' in line:
                        fingerprints[keyfile] = line.strip()
            except:
                pass

    html = f"""HTTP/1.1 200 OK\r
Content-Type: text/html\r
\r
<!DOCTYPE html>
<html>
<head><title>SSH Dark Tunnel – Dropbear</title></head>
<body>
<h1>SSH Tunnel Active</h1>
<p><b>Username:</b> root</p>
<p><b>Password:</b> changeme</p>
<p><b>Tunnel Host:</b> open-shh.onrender.com:443 (wss)</p>
<p><b>SNI:</b> applynow.hdfc.bank.in</p>
<p><b>Proxy command:</b> <code>./ws_ssh_proxy.py</code></p>
<p><b>Host key fingerprints:</b></p>
<pre>"""
    for key, fp in fingerprints.items():
        html += f"{key}: {fp}\n"
    html += """</pre>
<p>Connect with: <code>ssh -o ProxyCommand='./ws_ssh_proxy.py' root@dummy</code></p>
</body>
</html>"""
    writer.write(html.encode())
    await writer.drain()
    writer.close()

# ------------------------------------------------------------
# WebSocket relay (unchanged)
# ------------------------------------------------------------
class WebSocketRelay:
    def __init__(self, cr, cw):
        self.cr, self.cw = cr, cw
        self.sr = self.sw = None

    async def handle(self):
        try:
            data = b''
            while b'\r\n\r\n' not in data:
                c = await self.cr.read(4096)
                if not c: return
                data += c
            headers = data.decode(errors='ignore').split('\r\n')
            if not headers[0].startswith('GET'): return
            ws_key = None
            for h in headers:
                if h.startswith('Sec-WebSocket-Key:'):
                    ws_key = h.split(':',1)[1].strip()
            if not ws_key:
                ws_key = base64.b64encode(os.urandom(16)).decode()
            acc = base64.b64encode(hashlib.sha1((ws_key + MAGIC.decode()).encode()).digest()).decode()
            resp = f'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {acc}\r\n\r\n'
            self.cw.write(resp.encode()); await self.cw.drain()
            self.sr, self.sw = await asyncio.open_connection(SSH_HOST, SSH_PORT)
            await asyncio.gather(self.client_to_ssh(), self.ssh_to_client())
        except: pass
        finally: self.close()

    # ... (keep all existing methods: read_frame, mkframe, client_to_ssh, ssh_to_client, close)
    async def read_frame(self):
        hdr = await self.cr.readexactly(2)
        op = hdr[0] & 0x0F
        length = hdr[1] & 0x7F
        if length == 126: length = struct.unpack('!H', await self.cr.readexactly(2))[0]
        elif length == 127: length = struct.unpack('!Q', await self.cr.readexactly(8))[0]
        mask = bool(hdr[1] & 0x80)
        mkey = await self.cr.readexactly(4) if mask else None
        payload = await self.cr.readexactly(length)
        if mask and mkey:
            payload = bytes(b ^ mkey[i%4] for i,b in enumerate(payload))
        return op, payload

    def mkframe(self, payload, op=0x2):
        f = bytearray([0x80 | op])
        l = len(payload)
        if l < 126: f.append(l)
        elif l < 65536: f.extend([126, (l>>8)&0xFF, l&0xFF])
        else: f.extend([127]) + struct.pack('!Q', l)
        f.extend(payload)
        return bytes(f)

    async def client_to_ssh(self):
        try:
            while True:
                op, payload = await self.read_frame()
                self.sw.write(payload); await self.sw.drain()
        except: pass
        finally: self.sw and self.sw.close()

    async def ssh_to_client(self):
        try:
            while True:
                data = await self.sr.read(4096)
                if not data: break
                self.cw.write(self.mkframe(data)); await self.cw.drain()
        except: pass
        finally: self.cw.close()

    def close(self):
        try: self.cw.close()
        except: pass
        try: self.sw.close()
        except: pass

async def handle_client(r,w):
    await WebSocketRelay(r,w).handle()

async def main():
    # Start health‑check server (HTTP on 8081)
    health_srv = await asyncio.start_server(handle_health, '0.0.0.0', 8081)
    # Start WebSocket proxy (plain WebSocket, nginx terminates TLS)
    ws_srv = await asyncio.start_server(handle_client, HOST, PORT)
    await asyncio.gather(health_srv.serve_forever(), ws_srv.serve_forever())

if __name__ == '__main__':
    asyncio.run(main())
