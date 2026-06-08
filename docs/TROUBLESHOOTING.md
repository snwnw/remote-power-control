# Troubleshooting

Every symptom below was hit during this build, and each was non-obvious. Each
entry: what you see, why, and the fix.

---

## Linux won't deep-sleep / wakes itself immediately

**Why:** sleep state isn't `deep`, or a USB/NIC device is allowed to wake it on
spurious events.

**Fix:** set `mem_sleep_default=deep` in GRUB (`cat /sys/power/mem_sleep` should
show `[deep]`). Check `/proc/acpi/wakeup` for devices that shouldn't wake it.

---

## Linux WoL fails after a *long* sleep (r8169 bug)

**Symptom:** wake works after a short sleep or a manual suspend→resume cycle,
but after an overnight sleep the magic packet arrives (confirmed with
`tcpdump`) yet the machine stays down.

**Why:** kernel bug [#208033](https://bugzilla.kernel.org/show_bug.cgi?id=208033)
in the `r8169` Realtek driver — WoL only "arms" after a manual suspend/resume
cycle. The WoL flag (`Wake-on: g`) is still set and `deep` is still active; the
NIC simply isn't armed coming out of a cold sleep.

**What did *not* work:** switching to the out-of-tree `r8168` driver. It is
incompatible with kernel 6.17 (anything > 6.4) and killed networking entirely.
Reverted to `r8169`, blacklisted `r8168`
(`/etc/modprobe.d/blacklist-r8168.conf`), removed `r8168-dkms`.

**Current workaround (unverified across a full night):** a `systemd` sleep hook
at `/usr/lib/systemd/system-sleep/reload-r8169` that unloads and reloads
`r8169` around sleep and re-asserts the WoL flag, to mimic the manual cycle.

```sh
#!/bin/sh
# /usr/lib/systemd/system-sleep/reload-r8169   (chmod +x)
case "$1" in
  pre)
    ethtool -s enp3s0 wol g
    ;;
  post)
    modprobe -r r8169
    modprobe r8169
    ethtool -s enp3s0 wol g
    ;;
esac
```

**Open status:** still to be tested with a real overnight sleep. If it doesn't
hold, options are an RTC-based periodic wake, or a small always-on device that
issues the WoL locally (the server phone already does the latter for the
broadcast problem).

---

## Secure Boot vs NVIDIA vs autologin (Linux)

**Symptom:** NVIDIA driver and/or autologin misbehaving.

**Fix:** disabling Secure Boot in firmware resolved the combination on this
hardware.

---

## Remote wake over VPN does nothing (but sleep works)

**Symptom:** over the VPN, sleep works but wake doesn't. Curiously, wake *did*
work if you tried it immediately after the machine went to sleep.

**Why:** WireGuard is layer-3 and does not forward a layer-2 broadcast, so the
magic packet can't be broadcast across the tunnel. The "immediately after"
case worked only because the router's ARP cache still mapped the machine's IP
to its MAC, letting a unicast packet through; once the ARP entry expired
(minutes later) the sleeping NIC no longer answered ARP and the packet was
dropped. The router can't pin a static ARP entry.

**Fix:** the always-on **server phone** on the LAN. The remote phone makes an
HTTP call (point-to-point, fine over the VPN) and the server phone emits the
magic packet locally as a broadcast — no ARP dependency. This is the core of
the project.

---

## Sleep button hangs for ~5 seconds

**Symptom:** pressing sleep spins for about 5 seconds before finishing.

**Why:** the server was waiting for the SSH process to finish, but a machine
going to sleep drops the connection without a clean close, so SSH sat on its
connect timeout.

**Fix:** fire-and-forget SSH — launch with `ConnectTimeout=2` and don't wait
(`subprocess.Popen`, return immediately). `/sleep` now responds instantly. See
`server/app.py` (`ssh_fire`).

> A `getWifiIPAddress()`-based shortcut that polled the server with
> `sendHttpRequest()` to time the tunnel handshake also hung on mobile data,
> because that call has no short connect timeout and waited out `ETIMEDOUT` on
> 4G. The fix there was to drop the poll and use a fixed `wait()`.

---

## Pressing "sleep" wakes Windows (screen stays black)

**Symptom:** with the machine asleep, pressing sleep brings Windows *up* (fans
on, no display) instead of keeping it asleep.

**Why:** the Realtek NIC was set to wake on *any* inbound packet. The SSH
"sleep" packet woke the machine, but SSH couldn't complete the hibernate in
time, leaving it powered on without display.

**Fix:** Device Manager → the NIC → Power Management → **"Only allow a magic
packet to wake the computer"**, and Advanced → **"Wake on pattern match" =
Disabled** (keep "Wake on Magic Packet" enabled). Wake still works; the SSH
packet no longer wakes it.

---

## Server phone dies overnight (refused / timeout in the morning)

**Symptom:** in the morning the shortcut fails. A *"connection refused"* means
the phone is reachable but nothing is listening (the Flask/SSH process died);
a *timeout* means the phone itself was unreachable (Wi-Fi slept).

**Why:** Android killed the whole Termux process overnight, and deep sleep
dozed the Wi-Fi radio. (Both `sshd` and the Flask server died together because
both live inside Termux.)

**Fix (combine all):**
- Keep the phone **on the charger** — Doze does not run while charging.
- **Autostart** enabled for Termux and Termux:Boot; battery **unrestricted**;
  **lock** the Termux card in Recents.
- Hold `termux-wake-lock`.
- Run a **keepalive ping** to the router every 30s (in `start-wol.sh`) so the
  Wi-Fi radio stays associated.
- Disable Wi-Fi auto-switching features so they don't switch away from Wi-Fi.
- Last resort (some vendor ROMs): disable the manufacturer's "optimization"
  setting that aggressively kills background apps.

---

## On-demand VPN request fires before the tunnel is up

**Symptom:** on mobile data the request occasionally fails.

**Why:** the `wait()` after raising the tunnel was shorter than the WireGuard
handshake.

**Fix:** raise `wait()` (e.g. 1500 → 2500 ms). Going below ~1500 ms on mobile
tends to misfire. If you want it both fast and reliable instead of a fixed
wait, prefer split tunneling (see `DECISIONS.md`).
