#!/usr/bin/env python3
"""Spiral comet pattern for the L930 strip wrapped in a coil.

A bright comet head with a fading tail chases around the 50-segment
spiral, one encrypted update per tick (~200 ms), applied in place with a
fixed effect id (no blink/restart). Runs forever until killed; --ticks N
limits the number of ticks (one revolution = 50 ticks).

Same TPAP_* env vars as tpap_proto.py; run with the tapo venv python.

    export TPAP_HOST=<strip-ip> TPAP_PORT=80 TPAP_TLS=0
    export TPAP_USER=<email> TPAP_PASS=<password>
    /home/nvidia/build-a-claw/tapo_env/bin/python spiral_pattern.py
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tpap_proto  # noqa: E402

N = 50                 # segments on the 5m strip
TICK_S = 0.20          # one update per 200 ms (~5 updates/s ceiling)
HEAD_ADVANCE = 1       # segments the head moves per tick
TAIL = 14              # comet tail length in segments
HUE = 100              # NVIDIA green
BASE = 4               # dim base glow under the tail
EFFECT_ID = "TapoStrip_screensync"  # fixed id -> in-place updates, no blink


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=0, help="stop after N ticks (0 = run forever)")
    ap.add_argument("--hue", type=int, default=HUE)
    ap.add_argument("--tail", type=int, default=TAIL)
    args = ap.parse_args()

    s = tpap_proto.Tapap(host=_env("TPAP_HOST"), username=_env("TPAP_USER"),
                         password=_env("TPAP_PASS"), port=int(_env("TPAP_PORT", "80")),
                         tls=_env("TPAP_TLS", "0") == "1")
    s.discover()
    s.authenticate()
    print(f"attached: {s.mac[:6]}... running spiral comet (hue {args.hue}, tail {args.tail})", flush=True)

    head = 0
    tick = 0
    try:
        while True:
            states = []
            for i in range(N):
                d = (head - i) % N  # distance behind the head
                if d == 0:
                    bri = 100
                elif d <= args.tail:
                    bri = int(BASE + (100 - BASE) * (1 - d / (args.tail + 1)) ** 1.5)
                else:
                    bri = BASE
                states.append([args.hue, 100, bri, 0])
            s.send("apply_segment_effect_rule", {
                "brightness": 100, "custom": 1, "deviceType": "strip",
                "display_colors": states[:4], "enable": 1, "id": EFFECT_ID,
                "name": "spiral-comet", "segments": list(range(N)),
                "states": states, "type": "none",
            })
            head = (head + HEAD_ADVANCE) % N
            tick += 1
            if tick % 50 == 0:
                print(f"tick {tick} (rev {tick // 50 + 1}) head={head}", flush=True)
            if args.ticks and tick >= args.ticks:
                break
            time.sleep(TICK_S)
    finally:
        # leave a calm dim green so the strip is not at 100% after the loop
        try:
            s.send("set_device_info", {"device_on": True, "brightness": 20,
                                       "hue": args.hue, "saturation": 100,
                                       "color_temp": 0})
        except Exception:
            pass
        print("stopped (left dim)", flush=True)


def _env(name, default=None):
    v = os.environ.get(name, default)
    if v is None:
        raise SystemExit(f"env var {name} not set")
    return v


if __name__ == "__main__":
    main()
