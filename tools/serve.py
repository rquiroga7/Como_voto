#!/usr/bin/env python3
"""Simple local web server for the generated site.

Usage:
    python serve.py [port]

Defaults to port 8080. The script changes into the ``docs/`` directory and
boots a :mod:`http.server` so the site can be previewed in a browser.
"""
import http.server
import socketserver
import socket
import os
import sys
import signal
import subprocess

port = 8080
if len(sys.argv) > 1:
    try:
        port = int(sys.argv[1])
    except ValueError:
        print("Invalid port, using 8080")

# Kill any process already holding the port
try:
    result = subprocess.run(
        ["fuser", "-k", f"{port}/tcp"],
        capture_output=True,
    )
except FileNotFoundError:
    # fuser not available; try lsof + kill
    try:
        out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True)
        pids = out.strip().split()
        for pid in pids:
            os.kill(int(pid), signal.SIGTERM)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

webdir = os.path.join(os.path.dirname(__file__), "..", "docs")
if not os.path.isdir(webdir):
    print(f"docs/ directory not found at {webdir}")
    sys.exit(1)

os.chdir(webdir)
handler = http.server.SimpleHTTPRequestHandler


class DualStackServer(socketserver.TCPServer):
    """Listens on both IPv4 and IPv6 loopback so ``localhost`` works on Windows
    regardless of whether the browser resolves it to 127.0.0.1 or ::1."""
    allow_reuse_address = True

    def server_bind(self):
        try:
            self.socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(("::", self.server_address[1], 0, 0))
        except (OSError, AttributeError):
            # Fall back to plain IPv4 if dual-stack is unavailable
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(("0.0.0.0", self.server_address[1]))
        self.server_address = self.socket.getsockname()


with DualStackServer(("::", port), handler) as httpd:
    print(f"Serving {webdir} at http://localhost:{port} (network: http://192.168.1.13:{port})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped")
