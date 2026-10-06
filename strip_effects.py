#!/usr/bin/env python3
"""High-level control for Tapo L920/L930 RGBIC light strips over TPAP.

Wraps the raw `apply_segment_effect_rule` / `set_device_info` calls with:
  * a ready-to-use built-in preset catalog (presets.py, 55 app effects)
  * a per-segment "color painting" helper (the L930's 50 addressable segments)

Imports `tpap_proto.py` directly and holds ONE authenticated session for the
whole run (no re-auth per call), so this must be run with a Python that has
the client deps (requests, cryptography, ecdsa) — i.e. your tapo venv:

    /path/to/tapo_env/bin/python strip_effects.py ...

Credentials come from the TPAP_* environment variables (same as tpap_proto.py).

Usage examples:
    export TPAP_HOST=<strip-ip> TPAP_PORT=80 TPAP_TLS=0
    export TPAP_USER=<email> TPAP_PASS=<password>
    PY=/path/to/tapo_env/bin/python     # python with requests/cryptography/ecdsa

    $PY strip_effects.py list                  # list available presets
    $PY strip_effects.py preset halloween      # run a named built-in preset
    $PY strip_effects.py preset candlelight
    $PY strip_effects.py rainbow               # per-segment rainbow
    $PY strip_effects.py gradient --from 100 --to 25 --bands 5
    $PY strip_effects.py solid --hue 25 --sat 100 --bri 100
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import presets as _presets
import tpap_proto  # sibling module: provides the Tapap client class

DEFAULT_SEGMENTS = 50  # L930 5m / L920 5m strip
_SESSION_ID = "TapoStrip_screensync"  # fixed id -> in-place update, no blink


def _env(name, required=False, default=""):
    v = os.environ.get(name, default)
    if required and not v:
        raise SystemExit(f"env var {name} is not set (export it first)")
    return v


def _session():
    s = tpap_proto.Tapap(
        host=_env("TPAP_HOST", required=True),
        username=_env("TPAP_USER", required=True),
        password=_env("TPAP_PASS", required=True),
        port=int(_env("TPAP_PORT", default="80")),
        tls=_env("TPAP_TLS", default="0") == "1",
    )
    s.discover()
    s.authenticate()
    return s


class Strip:
    """One connected strip, reusing a single TPAP session."""

    def __init__(self):
        self.s = _session()

    def _send(self, method, params=None):
        """Send a method; raise on non-zero device error_code."""
        try:
            return self.s.send(method, params or {})
        except RuntimeError as e:
            # tpap_proto.send raises 'Device error <code>: {...}' on -xxxx.
            raise RuntimeError(f"{method} failed: {e}")

    def info(self):
        return self._send("get_device_info").get("result", {})

    def solid(self, hue=25, saturation=100, brightness=100, on=True):
        """Plain single-color state (hue 0-360, sat 1-100, bri 1-100)."""
        self._send("set_device_info", {"device_on": on, "brightness": brightness,
                                       "hue": hue, "saturation": saturation,
                                       "color_temp": 0})

    def preset(self, name, brightness=None):
        """Run a named built-in preset from presets.py (verified device effect)."""
        name = name.lower()
        if name not in _presets.PRESETS:
            raise SystemExit(f"unknown preset {name!r}. Run: {sys.argv[0]} list")
        p = _presets.PRESETS[name]
        bri = p["brightness"] if brightness is None else brightness
        self._send("apply_segment_effect_rule", {
            "brightness": bri, "custom": 0, "display_colors": p["colors"],
            "enable": 1, "id": p["id"], "name": name,
        })
        time.sleep(1)
        se = self.info().get("segment_effect", {})
        print(f"{name}: enable={se.get('enable')} id={se.get('id')}")

    def custom(self, name, brightness, segments, states, etype="none",
               effect_id=_SESSION_ID):
        """Push a custom per-segment effect and confirm it took.

        Device rules (verified against an L930, fw 1.4.3):
          * `segments` must be CUMULATIVE band-end indices, e.g. 5 even bands
            over 50 segments -> [9,19,29,39,49]; full 50 -> [0..49].
          * `display_colors` must be <= 4 entries (5+ returns -1008 PARAMS).
          * a FIXED `id` updates colors in place with no blink/restart.
        """
        if len(segments) != len(states):
            raise ValueError("segments and states must have equal length")
        self._send("apply_segment_effect_rule", {
            "brightness": brightness, "custom": 1, "deviceType": "strip",
            "display_colors": states[:4], "enable": 1, "id": effect_id,
            "name": name, "segments": segments, "states": states, "type": etype,
        })
        time.sleep(1)
        se = self.info().get("segment_effect", {})
        if not (se.get("enable") == 1 and se.get("id") == effect_id):
            raise RuntimeError(f"effect not active in readback: {json.dumps(se)}")
        return se

    def rainbow(self, total=DEFAULT_SEGMENTS, brightness=100):
        """Full-resolution rainbow, one hue per segment."""
        ends = list(range(total))
        states = [[(i * 360 // total) % 360, 100, brightness, 0] for i in range(total)]
        self.custom("rainbow", brightness, ends, states, etype="none")
        print("rainbow applied")

    def gradient(self, hue_from, hue_to, bands=5, total=DEFAULT_SEGMENTS,
                 brightness=90):
        """A smooth left->right gradient between two hues across `bands`."""
        ends = [round((i + 1) * total / bands) - 1 for i in range(bands)]
        states = []
        for i in range(bands):
            t = i / (bands - 1) if bands > 1 else 0
            hue = (int(hue_from + (hue_to - hue_from) * t)) % 360
            states.append([hue, 100, brightness, 0])
        self.custom("gradient", brightness, ends, states, etype="none")
        print(f"gradient {hue_from}->{hue_to} over {bands} bands applied")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list built-in presets")

    sp = sub.add_parser("preset", help="run a named preset")
    sp.add_argument("name")
    sp.add_argument("--brightness", type=int, default=None)

    sr = sub.add_parser("rainbow", help="per-segment rainbow")
    sr.add_argument("--total", type=int, default=DEFAULT_SEGMENTS)
    sr.add_argument("--bri", type=int, default=100)

    sg = sub.add_parser("gradient", help="left->right hue gradient")
    sg.add_argument("--from", dest="hue_from", type=int, required=True)
    sg.add_argument("--to", dest="hue_to", type=int, required=True)
    sg.add_argument("--bands", type=int, default=5)
    sg.add_argument("--total", type=int, default=DEFAULT_SEGMENTS)
    sg.add_argument("--bri", type=int, default=90)

    ss = sub.add_parser("solid", help="plain single color")
    ss.add_argument("--hue", type=int, default=25)
    ss.add_argument("--sat", type=int, default=100)
    ss.add_argument("--bri", type=int, default=100)

    a = ap.parse_args()
    if a.cmd == "list":
        print(", ".join(sorted(_presets.PRESETS)))
        return
    st = Strip()
    if a.cmd == "preset":
        st.preset(a.name, a.brightness)
    elif a.cmd == "rainbow":
        st.rainbow(a.total, a.bri)
    elif a.cmd == "gradient":
        st.gradient(a.hue_from, a.hue_to, a.bands, a.total, a.bri)
    elif a.cmd == "solid":
        st.solid(a.hue, a.sat, a.bri)
        print(f"solid hue={a.hue} sat={a.sat} bri={a.bri}")


if __name__ == "__main__":
    main()
