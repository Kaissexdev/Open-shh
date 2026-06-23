#!/usr/bin/env python3
import asyncio
import hashlib
import base64
import struct
import os

HOST = '0.0.0.0'
PORT = 8080
SSH_HOST = '127.0.0.1'
SSH_PORT = 22
WEBSOCKET_MAGIC = b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

class WebSocketRelay:
    def __init__(self, reader, writer):
        self.client_reader = reader
        self.client_writer = writer
        self.ssh_reader = None
        self.ssh_writer = None

    async def handle(self):
        try:
            # Step 1: read the HTTP upgrade request
            request_data = b''
            while b'\r\n\r\n' not in request_data:
                chunk = await self.client_reader.read(4096)
                if not chunk:
                    return
                request_data += chunk
                if len(request_data) > 8192:
                    return  # too large

            # Parse headers to extract WebSocket key
            headers = request_data.decode('utf-8', errors='ignore').split('\r\n')
            if len(headers) < 1 or not headers[0].startswith('GET'):
                return
            ws_key = None
            for h in headers[1:]:
                if h.startswith('Sec-WebSocket-Key:'):
                    ws_key = h.split(':', 1)[1].strip()
                    break
            if not ws_key:
                # Client didn't send key – we can still respond, but RFC requires it.
                # We'll generate one if missing, but usually it's present.
                ws_key = base64.b64encode(os.urandom(16)).decode()

            # Step 2: compute accept key and send 101 Switching Protocols
            accept_key = base64.b64encode(
                hashlib.sha1((ws_key + WEBSOCKET_MAGIC.decode()).encode()).digest()
            ).decode()
            response = (
                'HTTP/1.1 101 Switching Protocols\r\n'
                'Upgrade: websocket\r\n'
                'Connection: Upgrade\r\n'
                'Sec-WebSocket-Accept: ' + accept_key + '\r\n'
                '\r\n'
            )
            self.client_writer.write(response.encode())
            await self.client_writer.drain()

            # Step 3: connect to SSH
            ssh_reader, ssh_writer = await asyncio.open_connection(SSH_HOST, SSH_PORT)
            self.ssh_reader = ssh_reader
            self.ssh_writer = ssh_writer

            # Step 4: bidirectional relay with WebSocket framing
            # Run two tasks concurrently
            await asyncio.gather(
                self.client_to_ssh(),
                self.ssh_to_client()
            )
        except Exception:
            pass
        finally:
            self.close()

    async def client_to_ssh(self):
        try:
            while True:
                # Read a WebSocket frame
                frame = await self.read_frame(self.client_reader)
                if frame is None:
                    break
                # Unmasked payload
                payload = frame[1]
                self.ssh_writer.write(payload)
                await self.ssh_writer.drain()
        except:
            pass
        finally:
            if self.ssh_writer:
                self.ssh_writer.close()

    async def ssh_to_client(self):
        try:
            while True:
                data = await self.ssh_reader.read(4096)
                if not data:
                    break
                # Create a WebSocket frame (binary, FIN, unmasked from server)
                frame = self.create_frame(data, opcode=0x2)  # binary
                self.client_writer.write(frame)
                await self.client_writer.drain()
        except:
            pass
        finally:
            if self.client_writer:
                self.client_writer.close()

    async def read_frame(self, reader):
        header = await reader.readexactly(2)
        if not header:
            return None
        first_byte, second_byte = header[0], header[1]
        fin = (first_byte >> 7) & 1
        opcode = first_byte & 0x0F
        mask = (second_byte >> 7) & 1
        payload_len = second_byte & 0x7F

        if payload_len == 126:
            raw = await reader.readexactly(2)
            payload_len = struct.unpack('!H', raw)[0]
        elif payload_len == 127:
            raw = await reader.readexactly(8)
            payload_len = struct.unpack('!Q', raw)[0]

        if mask:
            masking_key = await reader.readexactly(4)
        else:
            masking_key = None

        payload = await reader.readexactly(payload_len)
        if mask and masking_key:
            payload = bytearray(payload)
            for i in range(len(payload)):
                payload[i] ^= masking_key[i % 4]
            payload = bytes(payload)
        return (opcode, payload)

    def create_frame(self, payload, opcode=0x1):
        frame = bytearray()
        frame.append(0x80 | opcode)  # FIN + opcode
        length = len(payload)
        if length < 126:
            frame.append(length)
        elif length < (1 << 16):
            frame.append(126)
            frame.extend(struct.pack('!H', length))
        else:
            frame.append(127)
            frame.extend(struct.pack('!Q', length))
        # Server → client frames are not masked
        frame.extend(payload)
        return bytes(frame)

    def close(self):
        try:
            self.client_writer.close()
        except:
            pass
        try:
            if self.ssh_writer:
                self.ssh_writer.close()
        except:
            pass

async def handle_client(reader, writer):
    relay = WebSocketRelay(reader, writer)
    await relay.handle()

async def healthcheck():
    # Simple HTTP server on port 8081 for platform health checks
    async def handle(reader, writer):
        try:
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK')
            await writer.drain()
        finally:
            writer.close()
    return await asyncio.start_server(handle, '0.0.0.0', 8081)

async def main():
    health_server = await healthcheck()
    ws_server = await asyncio.start_server(handle_client, HOST, PORT)
    print(f'WebSocket proxy listening on {HOST}:{PORT}')
    await asyncio.gather(health_server.serve_forever(), ws_server.serve_forever())

if __name__ == '__main__':
    asyncio.run(main())