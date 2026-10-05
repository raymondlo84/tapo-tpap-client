# tapo-tpap-client

A working reference client for the **TPAP** local-auth protocol that newer
TP-Link Tapo devices use. It lets you read and control Tapo devices that the
`tapo` library (and `tapo-mcp`) reject with
`Unauthorized: FORBIDDEN ... Third-Party Compatibility`.

The `tapo` Python/Rust library (verified through tag v0.9.0) implements only
`Aes`, `AesSsl`, and `Klap`. Devices that advertise
`tpap_preferred: true` / `encrypt_type: TPAP` — e.g. **P115** plugs and the
**L920/L930** RGB / RGBIC light strips — speak a different local protocol,
**SPAKE2+ PAKE on P-256** with an AEAD session on top. This client implements
that protocol end-to-end and has been proven live against a P115(US) plug and
an L930-5(US) light strip.

No Tapo cloud API involved — it talks straight to the device on your LAN.

## What's in here

| File | Purpose |
|------|---------|
| `tpap_proto.py` | The raw protocol client (self-contained, any method) |
| `strip_effects.py` | High-level L920/L930 helper: presets, per-segment rainbow/gradient |
| `presets.py` | Catalog of all 55 built-in strip effects (device-side IDs, verified) |
| `demos/heartbeat_pattern.py` | Ambient demo: a smooth "lub-dub" heartbeat pulse (default 20% peak) |
| `demos/spiral_pattern.py` | Ambient demo: a comet chasing around a coil-wound strip |
| `requirements.txt` | `requests`, `cryptography`, `ecdsa` |

## When you need this

If a Tapo device shows up in discovery but `tapo` / `tapo-mcp` returns
`FORBIDDEN ... Third-Party Compatibility`, and raw discovery reports
`encrypt_type: TPAP`, the mobile app still drives it (via the cloud) but
**local** control needs this client. Toggling the app's Third-Party Services
setting, power-cycling, or re-pairing will **not** fix a TPAP device — the
"Third-Party Compatibility" text is a hardcoded KLAP-403 message and a red
herring.

### Which of my devices need it?

Run raw discovery (no auth required) to see each device's protocol:

```python
import asyncio
from tapo import ApiClient

async def main():
    d = await ApiClient.discover_devices_raw("<LAN broadcast, e.g. lan-broadcast>", 10)
    async for r in d:
        v = r.get()
        m = v.message["result"]
        print(v.ip, m["device_model"],
              m["mgt_encrypt_schm"]["encrypt_type"],
              m.get("tpap_preferred"), m.get("tpap"))

asyncio.run(main())
```

A `TPAP` row with `tpap_preferred: True` and a `tpap` dict (`port`, `tls`,
`pake`) is a device this client can drive. `KLAP`/`AES` rows are the normal
case and don't need it.

## Install

Python 3.10+ with three wheels:

```bash
pip install -r requirements.txt
```

## Usage: raw client

Credentials are passed as environment variables — never hardcode them:

```bash
export TPAP_HOST=device-ip        # device IP
export TPAP_PORT=80              # from discovery tpap.port (plain HTTP)
export TPAP_TLS=0                # from discovery tpap.tls (1 = TLS)
export TPAP_USER=<tapo account email>
export TPAP_PASS=<tapo account password>

# run from the repo root (the client reads no other modules)
python tpap_proto.py [method [json_params]]
```

The method defaults to `get_device_info`. On success you'll see
`AUTH OK session=... seq=...` on stderr followed by the decrypted JSON result.

### Examples (verified live)

```bash
# Read a device
python tpap_proto.py get_device_info

# Read a P115 plug's power
python tpap_proto.py get_current_power

# Turn a strip on and set a color. NOTE: flat params, NOT wrapped in "state".
python tpap_proto.py set_device_info \
  '{"device_on":true,"brightness":100,"hue":25,"saturation":100,"color_temp":0}'

# Run a built-in strip effect (id from presets.py)
python tpap_proto.py apply_segment_effect_rule \
  '{"brightness":50,"custom":0,"display_colors":[[20,87,100,0],[20,87,100,0],[20,87,100,0]],"enable":1,"id":"TapoStrip_6dJUyTqdQb69WMTtYfmhXp","name":"volcano"}'
```

## Usage: strip helper (L920 / L930)

`strip_effects.py` wraps the raw client with a single authenticated session
per run (no re-auth per call) and verified effect shapes:

```bash
PY=/path/to/tapo_env/bin/python   # a python with requests/cryptography/ecdsa

$PY strip_effects.py list                          # the 55 built-in presets
$PY strip_effects.py preset halloween              # run a named preset
$PY strip_effects.py preset candlelight --brightness 70
$PY strip_effects.py rainbow                       # 50-segment full rainbow
$PY strip_effects.py gradient --from 100 --to 25 --bands 8   # green->orange
$PY strip_effects.py solid --hue 25 --sat 100 --bri 100      # plain orange
```

## Ambient demos (`demos/`)

Self-contained demo scripts for the L930 (best when the strip is wound in a
spiral/coil). Each runs until killed, then leaves the strip dim:

```bash
PY=/path/to/tapo_env/bin/python   # a python with requests/cryptography/ecdsa

# smooth "lub-dub" heartbeat, 6fps, peak 20% (time-locked pacing; the wire
# ceiling is ~6 updates/sec because each frame is one encrypted round-trip)
$PY demos/heartbeat_pattern.py    # --peak 40  --hue 100  --ticks 300

# comet chasing around the coil, one revolution ~10s
$PY demos/spiral_pattern.py       # --hue 100  --tail 8  --ticks 100
```

They work from any cwd (they locate `tpap_proto.py` relative to the repo).

For a **persistent** ambient (survives reboots and is independent of any
shell), run a demo under systemd the same way `nvidia-light` does, e.g.:

```ini
# ~/.config/systemd/user/strip-heartbeat.service
[Unit]
Description=L930 strip heartbeat - smooth red lub-dub ambient
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
Environment=TPAP_HOST=device-ip
Environment=TPAP_PORT=80
Environment=TPAP_TLS=0
ExecStart=<venv-python> <repo>/demos/heartbeat_pattern.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now strip-heartbeat
journalctl --user -u strip-heartbeat -f   # watch it
```

Credentials: `TPAP_USER`/`TPAP_PASS` env vars, falling back to the
`TAPO_MCP_USERNAME`/`TAPO_MCP_PASSWORD` lines of
`~/.openclaw/settings/tapo-mcp.env` (the same file tapo-mcp uses).

### Built-in presets

`presets.py` carries all 55 app-defined effect templates with their
device-side IDs (e.g. `TapoStrip_...`), parsed from the `tapo` crate source
and verified live on an L930-5(US): `siren`, `fireworks`, `volcano`, `star`,
`candlelight`, `halloween`, `disco`, `dancing`, `electro_dance`, `bonfire`,
`dreamland`, `universe`, `movie`, `game`, `forest`, `snow`, and 40 more —
see `strip_effects.py list`.

Presets use `custom: 0` (the device looks them up by ID). Colors in
`display_colors` are `[hue, saturation, brightness, 0]`, hue 0–360.

## Per-segment "color painting" (the L930's real superpower)

The L930/L920 strips have **50 addressable segments** and accept custom
per-segment effects via `apply_segment_effect_rule` with `custom: 1`.
Verified device rules (L930-5 US, fw 1.4.3):

- **`segments` must be cumulative band-end indices** — e.g. 5 even bands over
  50 segments → `[9, 19, 29, 39, 49]`; full resolution (one color per
  segment) → `[0, 1, …, 49]`. Passing a single count (e.g. `[300]`) is
  rejected.
- **`display_colors` must have ≤ 4 entries** — 5 or more returns
  **`error_code -1008 PARAMS`** (the "PARAMS" error; the device gives no more
  detail).
- **`states`** is one `[hue, sat, bri, 0]` per band.
- **Use a fixed `id`** (e.g. `TapoStrip_screensync`): the device then updates
  colors **in place with no restart/blink**. A fresh id each call re-creates
  the effect and produces a visible flash.
- Effect type `none` = static custom painting. (`chasing`/`breathe` etc.
  exist but the static path is what per-segment rendering needs.)

```python
import strip_effects
st = strip_effects.Strip()
# one color per segment: full rainbow
st.rainbow()
# or manual:
ends = [9, 19, 29, 39, 49]                    # 5 even bands
states = [[100,100,90,0],[60,100,90,0],
          [25,100,90,0],[25,100,90,0],[25,100,90,0]]
st.custom("my-scene", 90, ends, states)
```

**Performance ceiling:** each update is one encrypted round-trip (measured
155–200 ms on LAN; 1-band whole-strip payloads are fastest), so the
practical rate is **~5–6 updates/sec** with time-locked pacing. Smooth
flowing gradients are not achievable on this hardware; calm,
slowly-changing ambient content (screen-sync ambilight, GPU-state
gradients, the `demos/`) works beautifully. Smooth flowing gradients are not achievable on this hardware;
calm, slowly-changing ambient content (screen-sync ambilight, GPU-state
gradients) works beautifully.

## Method names are snake_case

TPAP methods are **snake_case**: `get_device_info`, `get_device_usage`,
`get_current_power`, `set_device_info`, `apply_segment_effect_rule`,
`set_lighting_effect`. Using camelCase (`getDeviceInfo`) returns
`error_code -1002`. (Bug fix 2026-10-05: the raw client's no-arg default was
`getDeviceInfo`, which fails — it now defaults to `get_device_info`.)

## Flat `set_device_info` params (color bulbs & strips)

For RGB/RGBIC devices, set color with `set_device_info` and a **flat** param
object — the same shape the `tapo` Rust builder
(`ColorLightSetDeviceInfoParams`) serializes:

```json
{"device_on": true, "brightness": 100, "hue": 25, "saturation": 100, "color_temp": 0}
```

Do **not** wrap it in `{"state": {...}}`. The wrapped form is accepted with
`error_code 0` but the device silently ignores it (state does not change).
Hue is 0–360, saturation 1–100, `color_temp` 2500–6500 (set `0` when using
hue/saturation). Setting hue/saturation also turns the device on and clears
any active lighting effect.

## Troubleshooting

- **`pake_share` fails with `error_code -2203`** (and `failedAttempts` /
  `remainAttempts`): that is a SPAKE2+ confirmation mismatch — treat it as a
  **wrong credential**, not a crypto bug. The recurring real cause is a
  shell-mangled password from `source .env` (quotes, `!`, `$`, whitespace).
  Pass the exact bytes as the env var:
  `P=$(grep -E '^TAPO_MCP_PASSWORD=' <envfile> | cut -d= -f2-)`, then
  `TPAP_PASS=*** — do not `source` the file. Verify before blaming the
  protocol: `printf '%s' "$P" | wc -c` (length) and
  `tr -d '\11\12\15\40-\176' | wc -c` (non-printing chars = 0).
  **Each failed `pake_share` consumes one of the device's limited login
  attempts**, so get the bytes right before retrying.

- **`error_code -1008 PARAMS` on `apply_segment_effect_rule`**: wrong
  payload shape — check the cumulative `segments` indices and the ≤4
  `display_colors` cap above.

- **`error_code -1002`**: camelCase method name; use snake_case.

- **`FORBIDDEN` from the normal `tapo`/`tapo-mcp` path**: device-side
  protocol gap (TPAP), not a container or network bug. Use this client.

- **Wrong port / TLS**: honor the discovery `tpap.port` / `tpap.tls`. A
  P115 uses port 80 plain HTTP; other devices may use 443 + TLS.

- **Works in the app ≠ local access is on**: the app drives devices via the
  cloud path. Local access is a separate protocol negotiation.

## Wire protocol (summary)

1. `discover`: `POST /` `{"method":"login","params":{"sub_method":"discover"}}` →
   `result.mac`, `result.tpap.pake[]`. pake code → `passcode_type`:
   `0`→`default_userpw`, `2`→`userpw`, `3`→`shared_token`.
2. `pake_register`: `{"sub_method":"pake_register", username: md5hex("admin"),
   user_random: b64(32 random bytes), cipher_suites:[1],
   encryption:["aes_128_ccm","chacha20_poly1305","aes_256_ccm"],
   passcode_type, stok:null}` → `result.{extra_crypt, encryption, dev_random,
   dev_salt, dev_share, cipher_suites, iterations}`.
3. Credential derivation from `extra_crypt` (`password_shadow`
   `passwd_id` 2/3, or `password_sha_with_salt`).
4. **SPAKE2+ on P-256** with SEC1 points `M`/`N`; PBKDF2-HMAC-SHA256 to
   `(a,b)`, then `w=a%n`, `h=b%n`, `x` random; compute `L, R, Rp, Z, V`; build
   the transcript; derive confirmation + shared keys via HKDF; compare
   `user_confirm` vs the device's `dev_confirm`.
5. `pake_share`: `{"sub_method":"pake_share", user_share: b64(L),
   user_confirm}` → `result.{dev_confirm, start_seq, expired, stok}`.
6. **Session**: derive an AEAD key + base nonce from the shared secret via
   HKDF (per-cipher labels); requests are `u32be(seq) ‖ AEAD(JSON)`, posted
   to `/stok=<stok>/ds` as `application/octet-stream`; `seq` increments after
   each request. Response `rseq` is in the first 4 bytes; decrypt with the
   response's `rseq`.

## Upstream

This closes the local-control gap for TPAP devices pending upstream support
in the `tapo` crate (see mihai-dinculescu/tapo issue #657).

## Changelog

- **2026-10-05**: ambient demos can now run as systemd user services
  (persistent, restart-on-failure); `demos/heartbeat_pattern.py` picks up
  Tapo credentials from the tapo-mcp env file when `TPAP_USER`/`TPAP_PASS`
  are not set.

- **2026-10-05**: reorganized: ambient demo scripts moved into `demos/`
  (`heartbeat_pattern.py`, `spiral_pattern.py`); their imports now work from
  any cwd. Heartbeat got smooth time-locked 6fps pacing, 1-band payloads,
  and a 20%-brightness peak (measured: ~155 ms 1-band round-trip).

- **2026-10-05**: added `heartbeat_pattern.py` (lub-dub pulse, verified
  live) and `spiral_pattern.py` (comet-chase demo; both verified live on a
  coil-wound strip).

- **2026-10-05**: fixed the raw client's no-arg default method
  (`getDeviceInfo` → `get_device_info`; the old default fails with -1002).
  Added `strip_effects.py` (single-session helper) and `presets.py` (all 55
  built-in strip effects with verified device-side IDs). Documented the
  per-segment "color painting" protocol: 50 segments, cumulative band-end
  indices, ≤4 display colors (-1008), fixed id for blink-free in-place
  updates, ~4–5 updates/sec ceiling.
