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

Single self-contained file (`tpap_proto.py`). No Tapo cloud API involved — it
talks straight to the device on your LAN.

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

## Usage

Credentials are passed as environment variables — never hardcode them:

```bash
export TPAP_HOST=device-ip        # device IP
export TPAP_PORT=80              # from discovery tpap.port (plain HTTP)
export TPAP_TLS=0                # from discovery tpap.tls (1 = TLS)
export TPAP_USER=<tapo account email>
export TPAP_PASS=<tapo account password>

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

# Read back
python tpap_proto.py get_device_info
```

## Method names are snake_case

TPAP methods are **snake_case**: `get_device_info`, `get_device_usage`,
`get_current_power`, `set_device_info`. Using camelCase
(`getDeviceInfo`) returns `error_code -1002`.

## Color strips (L920 / L930): use flat `set_device_info` params

For RGB/RGBIC strips, set color with `set_device_info` and a **flat** param
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

The full, field-by-field protocol is documented in the `tapo-mcp-operations`
skill's `references/tpap-implementation.md`; this file is the runnable
reference.

## Upstream

This closes the local-control gap for TPAP devices pending upstream support
in the `tapo` crate (see mihai-dinculescu/tapo issue #657).

## Files

| File | Purpose |
|------|---------|
| `tpap_proto.py` | The reference client (self-contained) |
| `requirements.txt` | `requests`, `cryptography`, `ecdsa` |
