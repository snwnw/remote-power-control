#!/data/data/com.termux/files/usr/bin/python3
"""
Remote power-control server.

Runs on an always-on Android phone (Termux) that lives on the home LAN.
It receives simple HTTP commands and:

  * wakes machines with Wake-on-LAN magic packets (local L2 broadcast), and
  * sleeps machines with fire-and-forget SSH.

Why this exists: WireGuard is a layer-3 VPN and cannot carry a layer-2
broadcast, so a magic packet sent from outside the LAN never reaches a
sleeping NIC. A phone sitting on the LAN can emit that broadcast. The remote
phone hits this server over the VPN (point-to-point, like SSH), and the server
emits the broadcast locally. Remote wake == local wake.

Endpoints:
  GET /                       -> "ok"            (health check, no token)
  GET /wake?token=...         -> wake all machines
  GET /wake/<name>?token=...  -> wake one machine
  GET /sleep?token=...        -> sleep all machines
  GET /sleep/<name>?token=... -> sleep one machine
"""

import os
import socket
import subprocess

from flask import Flask, request, abort

app = Flask(__name__)

# --------------------------------------------------------------------------- #
# Config  (replace the placeholders with your own)                            #
# --------------------------------------------------------------------------- #

# Token is read from the environment so it never lives in source control.
#   export WOL_TOKEN="something-long-and-random"
TOKEN = os.environ.get("WOL_TOKEN", "changeme")

# SSH private key used to reach the machines for the sleep command.
KEY = os.path.expanduser("~/.ssh/id_ed25519")

# MAC addresses for Wake-on-LAN (":" or "-" separators both fine).
MACS = {
    "linux":   "AA:BB:CC:DD:EE:01",
    "windows": "AA:BB:CC:DD:EE:02",
}

# SSH target + the command that puts each machine to sleep.
# Linux suspends (passwordless via sudoers); Windows hibernates.
HOSTS = {
    "linux":   ("<linux-user>@<linux-ip>",     "sudo systemctl suspend"),
    "windows": ("<windows-user>@<windows-ip>", "shutdown /h"),
}

# Where to spray the magic packet. The limited broadcast reaches all hosts on
# the same L2 segment (the server phone is on the same LAN as the machines).
# If it doesn't reach, add your directed broadcast, e.g. "192.168.X.255".
BROADCAST_ADDRS = ("255.255.255.255",)
WOL_PORTS = (9, 7)

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def send_magic(mac: str) -> None:
    """Send a Wake-on-LAN magic packet for the given MAC."""
    mac = mac.replace(":", "").replace("-", "")
    packet = bytes.fromhex("ff" * 6 + mac * 16)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        for addr in BROADCAST_ADDRS:
            for port in WOL_PORTS:
                sock.sendto(packet, (addr, port))
    finally:
        sock.close()


def ssh_fire(host: str, command: str) -> None:
    """Fire-and-forget SSH.

    A machine going to sleep drops the SSH session before it can close
    cleanly, so waiting for the process only produces timeouts. We launch the
    command with a short connect timeout and return immediately, which keeps
    the HTTP response instant.
    """
    full = [
        "ssh",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=2",
        "-i", KEY,
        host,
        command,
    ]
    subprocess.Popen(full, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def require_token() -> None:
    if request.args.get("token") != TOKEN:
        abort(403)


# --------------------------------------------------------------------------- #
# Routes                                                                      #
# --------------------------------------------------------------------------- #


@app.route("/")
def health():
    # No token: used by the remote phone to probe tunnel readiness.
    return "ok\n"


@app.route("/wake")
def wake_all():
    require_token()
    for mac in MACS.values():
        send_magic(mac)
    return "wake sent: " + ", ".join(MACS) + "\n"


@app.route("/wake/<name>")
def wake_one(name):
    require_token()
    if name not in MACS:
        abort(404)
    send_magic(MACS[name])
    return "wake sent: " + name + "\n"


@app.route("/sleep")
def sleep_all():
    require_token()
    for host, command in HOSTS.values():
        ssh_fire(host, command)
    return "sleep sent: " + ", ".join(HOSTS) + "\n"


@app.route("/sleep/<name>")
def sleep_one(name):
    require_token()
    if name not in HOSTS:
        abort(404)
    host, command = HOSTS[name]
    ssh_fire(host, command)
    return "sleep sent: " + name + "\n"


if __name__ == "__main__":
    # Listen on all interfaces so the phone is reachable from the LAN / tunnel.
    app.run(host="0.0.0.0", port=8080)
