#!/data/data/com.termux/files/usr/bin/sh
#
# Termux:Boot startup script.
#
# Install:
#   1. Install the "Termux:Boot" app (F-Droid) and OPEN IT ONCE so Android
#      registers the boot hook.
#   2. Place this file at  ~/.termux/boot/start-wol.sh
#   3. chmod +x ~/.termux/boot/start-wol.sh
#
# It also covers the case of a fresh boot. It does NOT, by itself, survive
# Android killing Termux while running — for that, also do the battery /
# autostart hardening described in docs/SETUP.md and docs/TROUBLESHOOTING.md.

# Hold a wake lock so Android does not suspend the process or doze the Wi-Fi.
termux-wake-lock

# Start the SSH server so you can shell into the phone remotely (port 8022).
sshd

# Keepalive: ping the router every 30s so the Wi-Fi radio stays associated.
# Set this to your router/gateway address.
GATEWAY="your.router.ip"
( while true; do ping -c1 "$GATEWAY" >/dev/null 2>&1; sleep 30; done ) &

# Token the Flask server expects. Use a long random value, and do not commit it.
export WOL_TOKEN="change-me-to-a-long-random-string"

# Start the power-control server. Running it in the foreground keeps this boot
# service alive (Termux:Boot considers the script "done" when it exits).
cd ~/wol-server
python app.py
