# Remote Power Control

Wake and sleep two home laptops from a phone — on the local network **and** from
anywhere over the internet — using Wake-on-LAN, SSH, a tiny Flask proxy, and
WireGuard.

No cloud, no third-party service, no subscription. Just hardware you already own.

---

## What it does

From shortcuts on a phone you can:

- **Wake** the Linux laptop, the Windows laptop, or both (Wake-on-LAN magic packet).
- **Sleep** the Linux laptop, the Windows laptop, or both (SSH → suspend / hibernate).

It works the same whether the phone is on home Wi-Fi or out on mobile data. On
mobile data the request is carried over a WireGuard tunnel, and — this is the
whole trick — the tunnel comes up only for the moment the button is pressed.

---

## Architecture

```
  REMOTE PHONE (the one you carry)
  HTTP Shortcuts + WG Tunnel
        |
        |  (A) on home Wi-Fi:  HTTP straight to the server phone
        |  (B) on mobile data: HTTP through the WireGuard tunnel
        |
        v
  +------------------------- HOME LAN -------------------------------+
  |                                                                  |
  |   +----------------+   WireGuard server, public IP + Dynamic DNS |
  |   |     Router     |                                             |
  |   +-------+--------+                                             |
  |           |                                                      |
  |   +-------v--------+    WoL magic packet (LAN broadcast)         |
  |   |  SERVER PHONE  |--------------------------------> +--------+ |
  |   | Termux + Flask |    SSH (sleep)                   | Linux  | |
  |   |  :8080         |--------------------------------> | laptop | |
  |   | (always on,    |                                  +--------+ |
  |   |  on charger)   |    WoL magic packet              +--------+ |
  |   |                |--------------------------------> |Windows | |
  |   |                |    SSH (sleep)                   | laptop | |
  |   |                |--------------------------------> +--------+ |
  |   +----------------+                                             |
  +------------------------------------------------------------------+
```

The **server phone** is the key component. WireGuard is a layer-3 VPN and cannot
carry a layer-2 broadcast, so a Wake-on-LAN magic packet sent from outside the
LAN never reaches the sleeping NIC. A phone that lives permanently on the LAN
**can** emit that broadcast. The remote phone therefore never sends WoL directly —
it makes a normal HTTP request (point-to-point, just like SSH, which already
works over the VPN) to the server phone, and the server phone emits the magic
packet locally. **Remote wake becomes identical to local wake.**

---

## Hardware (this build)

| Role | Device | Notes |
|------|--------|-------|
| Linux machine | Dell G5, Ubuntu, i3 | Ethernet `enp3s0`, Realtek NIC, `r8169` driver, static IP |
| Windows machine | ASUS laptop | Realtek Ethernet, static IP |
| Server phone | Android + Termux | Always home on charger, on the LAN |
| Remote phone | Android | The one you carry; runs HTTP Shortcuts + WG Tunnel |
| Router | with WireGuard server | Public IP, built-in WireGuard, Dynamic DNS. **No static-ARP support.** |

> The two phones are interchangeable in principle — what matters is that **one
> stays home on the LAN (server)** and **one is carried (remote)**.

> Addresses below use placeholders like `<linux-ip>`, `<server-ip>`,
> `<router-ip>`, `<linux-user>`. Replace them with your own.

---

## How the clever bits work

- **Remote wake without broadcast routing.** See *Architecture* above: the
  always-on server phone turns an HTTP call into a local WoL broadcast.
- **On-demand VPN, only when needed.** The remote phone's shortcut detects the
  network type with zero special permissions (`getWifiIPAddress()` returns
  `null` on mobile data). On Wi-Fi it hits the server directly. On mobile data
  it brings the WireGuard tunnel up, fires the request, then takes the tunnel
  back down. See [`docs/SETUP.md`](docs/SETUP.md#remote-phone--http-shortcuts).
- **Fire-and-forget sleep.** A machine going to sleep drops the SSH session
  before it can close cleanly, so the server does **not** wait for SSH to
  return — it launches the command with a 2-second connect timeout and replies
  immediately. Otherwise every sleep press hung for ~5 s on a TCP timeout.
- **Windows wakes only on a magic packet.** By default the Realtek NIC woke
  Windows on *any* inbound packet — so the SSH "sleep" packet woke it instead of
  sleeping it. Restricting wake to magic-packet-only fixes that.

---

## Repository layout

```
remote-power-control/
├── README.md                  ← you are here
├── .gitignore
├── server/
│   ├── app.py                 ← the Flask power-control server (runs in Termux)
│   └── start-wol.sh           ← Termux:Boot startup script
└── docs/
    ├── SETUP.md               ← step-by-step setup for all four components
    ├── TROUBLESHOOTING.md     ← symptoms → fixes for the gotchas hit
    └── DECISIONS.md           ← the build log: what was tried, dropped, chosen
```

---

## Quick start

1. Prepare the two machines — see [`docs/SETUP.md`](docs/SETUP.md):
   Wake-on-LAN + SSH + passwordless suspend/hibernate + autologin.
2. Put [`server/app.py`](server/app.py) on the always-on phone and run it in
   Termux; set it to start on boot with [`server/start-wol.sh`](server/start-wol.sh).
3. On the carried phone, create HTTP Shortcuts pointing at the server, and add
   the on-demand-VPN scripts from [`docs/SETUP.md`](docs/SETUP.md#remote-phone--http-shortcuts).

---


## License

MIT — do whatever you like; no warranty. (Add a `LICENSE` file if you publish.)
