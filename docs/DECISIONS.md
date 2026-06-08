# Build log — decisions, dead ends, and final choices

A record of how this project actually came together: what was tried, what was
abandoned and why, and where each thread ended up. Useful both as project
history and as a map of the design space if you're building something similar.

---

## 1. Local wake / sleep — the foundation

**Goal:** wake and sleep both laptops from a phone on the home network.

**Result:** working early and stayed working.

- Linux: SSH server, key from the phone, passwordless `systemctl suspend`,
  autologin (GDM3), `mem_sleep_default=deep`, WoL armed via NetworkManager and
  re-asserted after boot by a dispatcher script. Secure Boot had to be disabled
  to make NVIDIA + autologin cooperate.
- Windows: OpenSSH server + firewall rule, key auth, WoL in the Realtek driver,
  `CONSOLELOCK 0` and registry autologin (no password on wake), `shutdown /h`
  to hibernate.
- Phone: Termux scripts + Termux:Widget buttons on the home screen.

This was the easy half. Everything after this was about making it work *from
outside the house* and making it *reliable*.

---

## 2. The broadcast-over-VPN problem

**Goal:** wake the machines while away from home, over the router's WireGuard
VPN.

**Symptom:** sleep over the VPN worked; wake didn't. But wake *did* work if
tried in the first moments after the machine slept.

**Diagnosis:**
- A Wake-on-LAN magic packet is an **L2 broadcast**; WireGuard is an **L3** VPN
  and won't carry it.
- The "works immediately" clue was the giveaway: right after sleep, the router's
  **ARP cache** still mapped the machine's IP → MAC, so a *unicast* packet got
  through. Once the ARP entry expired (minutes), the sleeping NIC stopped
  answering ARP and the packet was dropped.
- The router has **no static-ARP option**, so it couldn't be fixed
  on the router.

**Decision — local proxy on an always-on phone.** Put a tiny HTTP server
(Flask, in Termux) on a phone that lives on the LAN. The remote phone makes a
normal HTTP request over the VPN (point-to-point, exactly like the SSH that
already worked), and the server emits the magic packet **locally** as a
broadcast — no ARP dependency. **Remote wake becomes identical to local wake.**
This is the central idea of the whole project.

The server also handles sleep (SSH to each machine), so one server covers both
directions.

---

## 3. Setting up the server phone from scratch

The phone chosen as the server was bare — only Termux installed. So instead of
relying on pre-existing `wake.sh` / `sleep.sh` scripts, the logic was folded
directly into the Flask app: wake needs **no** SSH (a magic packet isn't
authenticated), while sleep needs an SSH key placed on both machines.

**Result:** `/wake`, `/wake/<name>`, `/sleep`, `/sleep/<name>`, plus a
no-auth `/` health endpoint. Token via query parameter.

---

## 4. VPN on the remote phone: split vs on-demand

This was the longest thread, with several wrong turns.

**The requirement, refined over several rounds:**
- On **Wi-Fi**: hit the server directly, no VPN at all.
- On **mobile data**: bring the VPN up, run the request, take the VPN down.

**Dead end A — "always on / auto-tunnel on mobile."** Simplest to configure,
but it means the VPN is up the entire time you're on mobile, and with
`AllowedIPs = 0.0.0.0/0` *all* phone traffic routes through home. Not wanted.

**The two viable shapes:**

- **Split tunnel** — `AllowedIPs = <lan-subnet>`. The tunnel is up on mobile
  but only **LAN-bound** traffic enters it; everything else goes direct. Effect:
  "only the button's request uses the VPN." Buttons stay instant and silent (no
  scripting needed). The tunnel sits up-but-empty when idle. *Recommended for
  simplicity.*
- **On-demand** — tunnel fully **down** when idle, up only for the press. This
  is what was chosen, accepting the trade-offs below.

**Dead end B — on-demand that raised the VPN unconditionally.** The first
on-demand script brought the tunnel up on *every* press, including on Wi-Fi —
which broke local control (the LAN request got pulled into a hairpin through the
tunnel). The fix was to make the script **conditional on network type.**

**Dead end C — `setWireguardTunnelState()`.** HTTP Shortcuts has a first-class
function for toggling a tunnel, but it targets the **official WireGuard app**
only. Since the VPN client here is **WG Tunnel**, that function does nothing;
WG Tunnel is driven instead through its **Remote App Control** broadcast intents
(`START_TUNNEL` / `STOP_TUNNEL` with a key).

**Network detection without a permission.** Reading the Wi-Fi **SSID** requires
Android location permission (and location services on) — fragile and annoying.
`getWifiIPAddress()` returns `null` on mobile data and a real IP on Wi-Fi, needs
**no** permission, and is exactly the signal required. This unlocked the clean
conditional.

**Dead end D — polling the server to time the handshake.** To avoid a blind
wait, the script polled the server with `sendHttpRequest()` until it answered,
then proceeded. On 4G this **hung** — that call has no short connect timeout and
sat out the full `ETIMEDOUT`. A `sendTCPPacket()` with a 400 ms timeout was
tried next; ultimately a simple fixed `wait()` (≈2 s, tunable) proved the least
fragile.

**Final on-demand shape:**
- *Run before:* if `getWifiIPAddress() === null` → `START_TUNNEL` intent →
  `wait(2000)`. On Wi-Fi, do nothing.
- *Run on success & on failure:* if on mobile → `STOP_TUNNEL` intent.

**Accepted cost:** adding scripting means the shortcut is no longer fully
"headless," so a brief progress indicator shows while the tunnel comes up. If
that ever becomes annoying, split tunneling remains a two-tap fallback that
removes the scripting, the wait, and the indicator entirely.

---

## 5. Making the buttons quiet

**Symptom:** tapping a shortcut opened a browser-style page and showed a
spinner.

**Decision:** Response Handling → **"Show nothing (run silently)"**. (A Toast is
the middle option if you want a one-line confirmation.) The on-demand scripting
later reintroduced a brief indicator — an accepted trade-off.

---

## 6. Fast sleep

**Symptom:** the sleep buttons spun ~5 s.

**Cause/decision:** the server was waiting on SSH to a machine that was already
dropping the connection as it slept. Switched to **fire-and-forget** SSH
(`ConnectTimeout=2`, `Popen`, return immediately). `/sleep` now answers
instantly. Wake was always instant (one UDP packet).

---

## 7. The "sleep wakes Windows" bug

**Symptom:** pressing sleep brought Windows up with a black screen.

**Cause:** the Realtek NIC was waking on *any* inbound packet, so the SSH
"sleep" packet woke it instead of letting it hibernate.

**Decision:** restrict the NIC to **magic-packet-only** wake and disable "wake on
pattern match." Fixed it without affecting normal wake. (This also retired the
earlier "Windows wakes without display" mystery — same root cause.)

---

## 8. Overnight reliability of the server phone

**Symptom:** by morning, both `sshd` and the Flask server were dead and Wi-Fi
had dropped.

**Diagnosis:** MIUI killed the entire Termux process overnight, and deep sleep
dozed the Wi-Fi radio — not three separate failures but one (Termux died, taking
both services with it).

**Decisions (layered):** keep the phone **on the charger** (Doze doesn't run
while charging) · Termux/Termux:Boot **autostart** + **unrestricted battery** +
**locked in Recents** · hold `termux-wake-lock` · a **keepalive ping** to the
router every 30 s · disable **WLAN+**. The legacy "keep Wi-Fi on during sleep"
toggle doesn't exist on this phone, so these replace it.

**Open status:** to be confirmed across a full night.

---

## 9. TV control over IR — dropped

**Goal (nice-to-have):** turn the Samsung TV on/off alongside the Linux machine
(TV vkl on `wake both` / `wake linux`, vykl on `sleep both` / `sleep linux`).
The TV is a 2015 Samsung with **no network — IR only** — and is connected to the
Linux box over HDMI, which (confirmed) can't carry a power signal.

**Findings:**
- The phone **does** have an IR blaster, and **Mi Remote** controls the TV fine.
- But **Xiaomi exposes no public IR API**, so MacroDroid/Tasker have **no IR
  action** — only the system Mi Remote app can use the blaster.
- Mi Remote offers only a whole-remote shortcut, no standalone power button and
  no widget.

**Options weighed:**
- *Mi Remote + Accessibility tap* (free): brittle (coordinate taps break on
  layout/theme changes, and fail when the screen is off/locked — exactly the
  sleep case).
- *Wi-Fi → IR blaster* (e.g. Broadlink, ~10–15 €): reliable, driven by the
  **server** on `wake`/`sleep`, independent of where the phone is — but costs
  money.

**Decision:** **dropped.** It's a nice-to-have, not part of the core goal
(powering the laptops from the phone), which already works. The Wi-Fi IR blaster
route is the way back in if it's ever revisited.

---

## 10. Where things landed

**Working:** local wake/sleep · remote wake/sleep over the VPN (via the server
phone proxy) · on-demand tunnel that stays down on Wi-Fi and lifts only for the
request on mobile · silent buttons · instant sleep · magic-packet-only Windows
wake.

**Outstanding:** Linux WoL after a full overnight sleep (`r8169` bug) — hook in
place, not yet verified.

**Dropped:** TV IR control.

**Elsewhere:** an Active Directory lab on the Windows machine's spare VMs — being
done in a separate effort.
