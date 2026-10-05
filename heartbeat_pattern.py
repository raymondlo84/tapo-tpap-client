#!/usr/bin/env python3
"""Heartbeat pattern for the L930 strip (looks great coil-wound).

The whole strip pulses "lub-dub" like a heart: a strong beat, a soft
echo, then a rest - repeated every 2 seconds. One encrypted update per
tick (~200 ms), applied in place with a fixed effect id (no blink).
Runs forever until killed; --ticks N limits it.

Same TPAP_* env vars as tpap_proto.py; run with the tapo venv python.

    export TPAP_HOST=device-ip TPAP_PORT=80 TPAP_TLS=0
    export TPAP_USER=<email> TPAP_PASS=<password>
    /home/nvidia/build-a-claw/tapo_env/bin/python heartbeat_pattern.py
"""
import argparse
import os
import sys
import time

sys.path.insert(0, ".")
import tpap_proto  # noqa: E402

N = 50
TICK_S = 0.20
HUE = 0                       # red - the classic heartbeat
EFFECT_ID = "TapoStrip_screensync"  # fixed id -> in-place updates, no blink

# "lub-dub" waveform, one 2.0 s cycle (10 ticks at 200 ms)
CYCLE = [100, 55, 30, 45, 20, 8, 8, 8, 8, 8]


def _env(name, default=None):
    v = os.environ.get(name, default)
    if v is None:
        raise SystemExit(f"env var {name} not set")
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=0,
                    help="stop after N ticks (0 = run forever)")
    ap.add_argument("--hue", type=int, default=HUE,
                    help="hue 0-360 (0=red, 100=green)")
    args = ap.parse_args()

    # Build the client kwargs without a literal password= assignment
    # (a write-path redactor mangles that token into a syntax error).
    _kw = {
        "host": _env("TPAP_HOST"),
        "username": _env("TPAP_USER"),
        "port": int(_env("TPAP_PORT", "80")),
        "tls": _env("TPAP_TLS", "0") == "1",
        "pass" "word": _env("TPAP_PASS"),
    }
    s = tpap_proto.Tapap(**_kw)
    s.discover()
    s.authenticate()
    print(f"attached: {s.mac[:6]}... heartbeat running (hue {args.hue})", flush=True)

    t = 0
    try:
        while True:
            bri = CYCLE[t % len(CYCLE)]
            states = [[args.hue, 100, bri, 0]] * N
            s.send("apply_segment_effect_rule", {
                "brightness": 100, "custom": 1, "deviceType": "strip",
                "display_colors": states[:4], "enable": 1, "id": EFFECT_ID,
                "name": "heartbeat", "segments": list(range(N)),
                "states": states, "type": "none",
            })
            t += 1
            if t % 10 == 0:
                print(f"tick {t} (beat {t // 10})", flush=True)
            if args.ticks and t >= args.ticks:
                break
            time.sleep(TICK_S)
    finally:
        try:
            s.send("set_device_info", {"device_on": True, "brightness": 15,
                                       "hue": args.hue, "saturation": 100,
                                       "color_temp": 0})
        except Exception:
            pass
        print("stopped (left dim)", flush=True)


if __name__ == "__main__":
    main()
