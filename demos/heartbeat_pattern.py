#!/usr/bin/env python3
"""Heartbeat pattern for the L930 strip (looks great coil-wound) - SMOOTH.

Smooth version: instead of a discrete 10-value staircase advanced once per
~400ms (send + sleep), brightness is a continuous lub-dub function of
wall-clock time, pushed as a single whole-strip (1-band) update as fast as
the wire allows (~6fps). Result: a fast sharp "lub", a soft "dub", a smooth
exponential fade, at an even cadence.

Brightness is capped at a peak (default 20%) so the pulse is a soft, dim
glow rather than a harsh flash. One beat every ~1.2 s (~50 BPM).
Runs until killed; --ticks N limits it. Leaves the strip dim on stop.

Same TPAP_* env vars as tpap_proto.py; run with the tapo venv python.
"""
import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tpap_proto  # noqa: E402

PERIOD_S = 1.2          # one cardiac cycle
FPS = 6.0               # target frame cadence (wire ceiling ~6.4)
FRAME_S = 1.0 / FPS
PEAK = 20               # peak brightness as a percent (0-100)
FLOOR = 0.06            # resting glow as a fraction of PEAK
HUE = 0                 # red - the classic heartbeat
EFFECT_ID = "TapoStrip_screensync"  # fixed id -> in-place updates, no blink


def brightness_at(t_in_cycle, peak):
    """Continuous lub-dub envelope, scaled to `peak` percent."""
    def exp_decay(dt, tau):
        return math.exp(-dt / tau) if dt >= 0 else 0.0
    lub = exp_decay(t_in_cycle, 0.22)          # fast sharp "lub" (t=0)
    dub = 0.45 * exp_decay(t_in_cycle - 0.32, 0.25)  # softer "dub" echo
    s = max(lub, dub, FLOOR)                    # 0..1 shape w/ small floor
    return int(round(peak * min(1.0, s)))


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
    ap.add_argument("--peak", type=int, default=PEAK,
                    help=f"peak brightness percent 0-100 (default {PEAK})")
    args = ap.parse_args()

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
    print(f"attached {s.mac[:6]}... smooth heartbeat @ {FPS:.0f}fps, "
          f"peak {args.peak}% (hue {args.hue})", flush=True)

    start = time.perf_counter()
    t = 0
    try:
        while True:
            # Time-based pacing: compute brightness from the wall clock so the
            # envelope is exact regardless of wire jitter, then sleep just the
            # remainder of this frame's period (send is the bulk of it).
            frame_start = time.perf_counter()
            now = time.perf_counter() - start
            bri = brightness_at(now % PERIOD_S, args.peak)
            states = [[args.hue, 100, bri, 0]]
            s.send("apply_segment_effect_rule", {
                "brightness": 100, "custom": 1, "deviceType": "strip",
                "display_colors": states[:4], "enable": 1, "id": EFFECT_ID,
                "name": "heartbeat", "segments": [49], "states": states,
                "type": "none",
            })
            elapsed = time.perf_counter() - frame_start
            if elapsed < FRAME_S:
                time.sleep(FRAME_S - elapsed)
            t += 1
            if t % int(FPS * PERIOD_S) == 0:
                print(f"tick {t} (beat {t // int(FPS * PERIOD_S)})",
                      flush=True)
            if args.ticks and t >= args.ticks:
                break
    finally:
        try:
            s.send("set_device_info", {"device_on": True,
                                       "brightness": max(2, args.peak // 10),
                                       "hue": args.hue, "saturation": 100,
                                       "color_temp": 0})
        except Exception:
            pass
        print("stopped (left dim)", flush=True)


if __name__ == "__main__":
    main()
