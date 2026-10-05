#!/usr/bin/env python3
"""Real-time coil clock for the coil-wound L930 (50 segments).

Renders the actual local time on the strip:
  - bright hub at the coil center
  - blue hour hand  (inner windings)
  - green minute hand (outer 55%)
  - amber second marker (outer ring, steps to the nearest LED each second)
  - dim floor everywhere else for contrast

Because the 50 LEDs lie along a ~15-turn spiral, each hand is the single
LED nearest the true clock angle (quantization ~ +/-10 min on the minute
hand - that is the resolution of a 50-LED clock). Pushes only when the
lit set changes (a few times per minute) plus a 5-min keepalive, well
under the ~6 updates/sec wire ceiling.

Run:   python coil/coil_clock.py            # foreground daemon
Stop:  python coil/coil_clock.py off        # leave the strip dim
"""
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root holds tpap_proto
import tpap_proto  # noqa: E402

SEG = 50
EFFECT_ID = "TapoStrip_coilclock"

seg = np.load(os.path.join(HERE, "segmap.npy"))
CX, CY = seg.mean(axis=0)
RAD = np.hypot(seg[:, 0] - CX, seg[:, 1] - CY).max()
UV = np.stack([(seg[:, 0] - CX) / RAD, (seg[:, 1] - CY) / RAD], axis=1)
THETA = np.arctan2(UV[:, 1], UV[:, 0])
R = np.hypot(UV[:, 0], UV[:, 1])

HUB = R < 0.17
HOUR = (R >= 0.17) & (R < 0.62)
MINUTE = R >= 0.45
SECONDS = R > 0.72


def ang_diff(a, b):
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


def nearest(mask, angle, w=0.45):
    idx = np.where(mask)[0]
    if idx.size == 0:
        return None
    d = np.array([ang_diff(THETA[k], angle) for k in idx])
    k = int(idx[int(np.argmin(d))])
    return k if float(d.min()) < w else None


def clock_states(now=None):
    now = now or time.localtime()
    minute = now.tm_min + now.tm_sec / 60.0
    hour = (now.tm_hour % 12) + minute / 60.0
    a_s = now.tm_sec / 60.0 * 2 * math.pi - math.pi / 2
    a_m = minute / 60.0 * 2 * math.pi - math.pi / 2
    a_h = hour / 12.0 * 2 * math.pi - math.pi / 2
    states = [[0, 0, 3, 0]] * SEG
    for k in np.where(HUB)[0]:
        states[k] = [0, 0, 100, 0]
    k = nearest(HOUR, a_h)
    if k is not None:
        states[k] = [200, 100, 100, 0]
    k = nearest(MINUTE, a_m)
    if k is not None:
        states[k] = [120, 100, 100, 0]
    k = nearest(SECONDS, a_s)
    if k is not None:
        states[k] = [35, 100, 100, 0]
    return states


def credentials():
    if os.environ.get("TPAP_USER") and os.environ.get("TPAP_PASS"):
        return
    envf = os.path.expanduser("~/.openclaw/settings/tapo-mcp.env")
    if os.path.exists(envf):
        vals = {}
        for line in open(envf):
            line = line.strip()
            if line.startswith("TAPO_MCP_USERNAME="):
                vals["TPAP_USER"] = line.split("=", 1)[1]
            elif line.startswith("TAPO_MCP_PASSWORD="):
                vals["TPAP_PASS"] = line.split("=", 1)[1]
        for k, v in vals.items():
            os.environ.setdefault(k, v)


def connect():
    _pw = os.environ.get("TPAP_PASS", "")
    s = tpap_proto.Tapap(
        host=os.environ["TPAP_HOST"], username=os.environ["TPAP_USER"],
        password=_pw,
        port=int(os.environ.get("TPAP_PORT", "80")),
        tls=os.environ.get("TPAP_TLS", "0") in ("1", "true"))
    s.discover()
    s.authenticate()
    return s


def push(s, states):
    s.send("apply_segment_effect_rule", {
        "brightness": 100, "custom": 1, "deviceType": "strip",
        "display_colors": states[:4], "enable": 1, "id": EFFECT_ID,
        "name": "coilclock", "segments": list(range(SEG)),
        "states": states, "type": "none"})


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "off":
        s = connect()
        push(s, [[0, 0, 0, 0]] * SEG)
        time.sleep(0.5)
        print("coil clock off")
        return
    credentials()
    s = connect()
    print("AUTH OK", flush=True)
    last, last_push = None, 0.0
    while True:
        try:
            now = time.localtime()
            st = clock_states(now)
            if st != last or time.time() - last_push > 300:
                push(s, st)
                last, last_push = st, time.time()
                print(f"{now.tm_hour:02d}:{now.tm_min:02d}:{now.tm_sec:02d} pushed",
                      flush=True)
            time.sleep(max(0.05, 1 - (time.time() % 1)))
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"error: {e!r}; re-auth in 5s", flush=True)
            time.sleep(5)
            try:
                s = connect()
                print("re-AUTH OK", flush=True)
            except Exception as e2:
                print(f"re-auth failed: {e2!r}", flush=True)
    try:
        s2 = connect()
        push(s2, [[0, 0, 0, 0]] * SEG)
    except Exception:
        pass
    print("exiting, strip dim", flush=True)


if __name__ == "__main__":
    main()
