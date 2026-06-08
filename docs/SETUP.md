# Setup

Four components to configure: the **Linux machine**, the **Windows machine**,
the **server phone**, and the **remote phone**. Do them in that order.

Throughout, replace the placeholders with your own values:

| Placeholder | Meaning |
|-------------|---------|
| `<linux-ip>` / `<windows-ip>` | the two laptops' LAN IPs |
| `<server-ip>` | the always-on server phone's LAN IP |
| `<router-ip>` | the router / gateway |
| `<linux-user>` / `<windows-user>` | the login on each laptop |
| `<lan-subnet>` | your LAN range, e.g. `192.168.0.0/24` |
| `<TOKEN>` | a long random string for `WOL_TOKEN` |

Reserve a static IP for each device in the router's DHCP so addresses don't drift.

---

## Linux machine

Goal: wakes on a magic packet, sleeps on an SSH command without a password,
and comes back to a usable desktop on its own.

1. **SSH server**

   ```bash
   sudo apt install openssh-server
   sudo systemctl enable --now ssh
   ```
   Add the server phone's public key to `~/.ssh/authorized_keys`.

2. **Passwordless suspend** — `/etc/sudoers.d/suspend` (edit with `sudo visudo -f`):

   ```
   <linux-user> ALL=(ALL) NOPASSWD: /usr/bin/systemctl suspend
   ```

3. **Deep sleep** — so the box truly sleeps but still listens for WoL. Add
   `mem_sleep_default=deep` to `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub`,
   then `sudo update-grub` and reboot. Verify:

   ```bash
   cat /sys/power/mem_sleep      # [deep] should be selected
   ```

4. **Wake-on-LAN, armed and persistent**

   ```bash
   sudo apt install ethtool
   ip link                       # find the interface, e.g. enp3s0
   sudo ethtool enp3s0 | grep Wake-on   # want: Wake-on: g
   ```
   With NetworkManager/netplan, set `wakeonlan: true` (netplan) or
   `wake-on-lan: magic`. The WoL flag is easily cleared after boot, so reassert
   it with a dispatcher script `/etc/NetworkManager/dispatcher.d/99-wol`:

   ```bash
   #!/bin/sh
   ethtool -s enp3s0 wol g
   ```
   `chmod +x` it.

5. **Autologin + Secure Boot.** Enable autologin in GDM3
   (`/etc/gdm3/custom.conf`). On this hardware, Secure Boot had to be **disabled**
   to get the NVIDIA driver and autologin working together.

6. **Test locally:** from another LAN host, `wakeonlan <mac>` to wake, and
   `ssh <linux-user>@<linux-ip> 'sudo systemctl suspend'` to sleep.

> See [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) for the `r8169` long-sleep WoL
> bug, which is the one outstanding hardware issue.

---

## Windows machine

Goal: wakes **only** on a magic packet, hibernates on an SSH command, and logs
in without a password prompt on wake.

1. **OpenSSH server** — install the "OpenSSH Server" optional feature, then:

   ```powershell
   Start-Service sshd
   Set-Service -Name sshd -StartupType Automatic
   ```
   Allow it through the firewall and add the server phone's key to
   `C:\Users\<windows-user>\.ssh\authorized_keys`.

2. **Wake-on-LAN in the NIC driver** — Device Manager → Network adapters →
   your Realtek adapter → **Properties**:
   - **Power Management** tab → check **"Allow this device to wake the
     computer"** *and* **"Only allow a magic packet to wake the computer"**.
   - **Advanced** tab → enable **"Wake on Magic Packet"**; set
     **"Wake on pattern match"** to **Disabled**.

   > The magic-packet-only restriction is essential. Without it the NIC wakes on
   > *any* inbound packet — including the SSH "sleep" packet — so pressing sleep
   > would wake the machine instead.

3. **No password on wake** — set `CONSOLELOCK` to `0` (so Windows doesn't lock
   on resume) and configure autologin via the registry.

4. **Hibernate as "sleep"** — the sleep command used is `shutdown /h`.

5. **Test locally:** `wakeonlan <mac>` to wake; `ssh <windows-user>@<windows-ip> 'shutdown /h'`
   to hibernate.

---

## Server phone — Termux

Goal: an always-on HTTP server on the LAN that turns requests into local WoL
broadcasts and SSH sleep commands, and that survives reboots and Android's
battery killer.

1. **Packages**

   ```bash
   pkg update -y && pkg upgrade -y
   pkg install -y python net-tools openssh
   pip install flask
   ```

2. **SSH key to reach the machines** (so sleep works):

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
   ssh-copy-id -i ~/.ssh/id_ed25519.pub <linux-user>@<linux-ip>      # Linux
   cat ~/.ssh/id_ed25519.pub                                         # copy this
   # then on Windows: append it to %USERPROFILE%\.ssh\authorized_keys
   ```
   Confirm both reach without a password prompt:
   ```bash
   ssh <linux-user>@<linux-ip> echo ok
   ssh <windows-user>@<windows-ip> echo ok
   ```

3. **The server** — put [`../server/app.py`](../server/app.py) in `~/wol-server/`,
   edit the `MACS` / `HOSTS` config at the top, then:

   ```bash
   export WOL_TOKEN="<TOKEN>"
   cd ~/wol-server && python app.py
   ```
   From the remote phone **on home Wi-Fi**, in a browser:
   - `http://<server-ip>:8080/` → `ok`
   - `http://<server-ip>:8080/wake?token=<TOKEN>` → both wake
   - `http://<server-ip>:8080/sleep?token=<TOKEN>` → both sleep

4. **Run detached** (so it survives the SSH session that started it, and so
   sleeping the machines doesn't kill it):

   ```bash
   termux-wake-lock
   cd ~/wol-server && nohup python app.py >~/wol.log 2>&1 &
   ```

5. **Start on boot** — put [`../server/start-wol.sh`](../server/start-wol.sh) at
   `~/.termux/boot/start-wol.sh`, `chmod +x` it, install **Termux:Boot** and
   **open it once**.

6. **Stop Android from killing it** (the single most important reliability step):
   - Enable **Autostart** for Termux and Termux:Boot.
   - Set the Termux battery policy to **No restrictions**.
   - In Recents, **lock** the Termux card so "clear all" doesn't kill it.
   - **Keep the phone on the charger.** Doze (which sleeps the Wi-Fi radio)
     does not run while charging.
   - Disable Wi-Fi auto-switching features that can drop the connection.

> The Wi-Fi "keep on during sleep" toggle doesn't exist on modern phones — the
> wake lock + charger + keepalive ping (in `start-wol.sh`) replace it.

---

## Remote phone — HTTP Shortcuts

Goal: home-screen buttons that work on Wi-Fi (direct) and on mobile data
(bring the VPN up only for the request).

### Shortcuts

Install **HTTP Shortcuts**. Create six shortcuts, each a **GET** request:

| Name | URL |
|------|-----|
| Wake both | `http://<server-ip>:8080/wake?token=<TOKEN>` |
| Wake Linux | `http://<server-ip>:8080/wake/linux?token=<TOKEN>` |
| Wake Windows | `http://<server-ip>:8080/wake/windows?token=<TOKEN>` |
| Sleep both | `http://<server-ip>:8080/sleep?token=<TOKEN>` |
| Sleep Linux | `http://<server-ip>:8080/sleep/linux?token=<TOKEN>` |
| Sleep Windows | `http://<server-ip>:8080/sleep/windows?token=<TOKEN>` |

Add each as a home-screen widget. For a quiet button, set **Response Handling →
On Success / On Failure → "Show nothing (run silently)"** (or a Toast if you
want brief feedback).

### VPN client (WG Tunnel)

Install **WG Tunnel** and import the WireGuard config from the router. For the
on-demand approach below you do **not** need WG Tunnel's auto-tunneling — the
shortcut drives the tunnel. Enable remote control so the shortcut can:

- WG Tunnel → Settings → **Android Integrations → Remote App Control** → enable,
  then tap the generated **key** to copy it. Note your **tunnel name**.
- Exclude WG Tunnel from battery optimization.

### On-demand VPN scripts

These go in each shortcut under **Scripting**. They detect the network with
`getWifiIPAddress()` (which is `null` on mobile data and needs **no** location
permission). On Wi-Fi they do nothing — the request goes straight to the LAN.
On mobile data they raise the tunnel, wait for the handshake, and (afterwards)
drop it.

**Run before Execution** — replace `KEY` and `TUNNEL_NAME`:

```javascript
if (getWifiIPAddress() === null) {            // null = on mobile data
  sendIntent({
    type: 'broadcast',
    action: 'com.zaneschepke.wireguardautotunnel.START_TUNNEL',
    packageName: 'com.zaneschepke.wireguardautotunnel',
    className: 'com.zaneschepke.wireguardautotunnel.core.broadcast.RemoteControlReceiver',
    extras: [
      { name: 'key',        type: 'string', value: 'KEY' },
      { name: 'tunnelName', type: 'string', value: 'TUNNEL_NAME' },
    ],
  });
  wait(2000);                                  // handshake; raise to 2500 if it misses
}
// On Wi-Fi: do nothing, the request goes direct to the LAN.
```

**Run on Success** *and* **Run on Failure** (identical in both, so the tunnel is
always taken back down):

```javascript
if (getWifiIPAddress() === null) {
  sendIntent({
    type: 'broadcast',
    action: 'com.zaneschepke.wireguardautotunnel.STOP_TUNNEL',
    packageName: 'com.zaneschepke.wireguardautotunnel',
    className: 'com.zaneschepke.wireguardautotunnel.core.broadcast.RemoteControlReceiver',
    extras: [
      { name: 'key',        type: 'string', value: 'KEY' },
      { name: 'tunnelName', type: 'string', value: 'TUNNEL_NAME' },
    ],
  });
}
```

> Adding scripting means the shortcut can no longer run fully "headless," so a
> brief progress indicator appears while the tunnel comes up. That is the
> inherent cost of true on-demand. If you'd rather keep buttons instant and
> silent, use **split tunneling** instead — see
> [`DECISIONS.md`](DECISIONS.md#vpn-on-the-remote-phone-split-vs-on-demand).

### Test

- **Mobile data** (Wi-Fi off): press a button → WG Tunnel comes up → request
  runs → tunnel goes back down (verify in WG Tunnel).
- **Wi-Fi**: press a button → instant, VPN is not touched.
