#!/usr/bin/env python3
"""Constellation drawing on the coil-wound L930 strip.

The strip is wound into a spiral inside the box, so its 50 segments form a
2-D constellation (measured by calibrate_markers.py -> segmap.npy). This
engine lights the segments that fall inside/outside a shape, so we can draw
real pictures with the strip: heart, star, smiley, bolt... plus animations
(snake, radar sweep, twinkle).

Usage (tapo venv python, from anywhere):
    python coil/draw.py static            # heart, star, smiley, bolt + photos
    python coil/draw.py show NAME         # push one static shape, leave it
    python coil/draw.py anim NAME         # 12-frame GIF of one animation
    python coil/draw.py off               # all dim

Static shapes: heart star smiley bolt spokes target pacman
Animations:  snake radar twinkle pacman planet clock

Requires: segmap.npy (run coil/calibrate_markers.py once, webcam pointed at
the coil), TPAP_HOST/TPAP_USER/TPAP_PASS env vars, and `fswebcam`.

Shapes are defined in normalized coil space (u,v in ~[-1,1], v down).
"""
import math
import os
import subprocess
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(HERE, "frames")
os.makedirs(FR, exist_ok=True)
SEG = 50
CAM = "fswebcam -d /dev/video0 -r 1280x720 -S --no-banner"  # tune to your camera

sys.path.insert(0, os.path.dirname(HERE))  # repo root holds tpap_proto
import tpap_proto  # noqa: E402
EFFECT_ID = "TapoStrip_draw"

seg = np.load(os.path.join(HERE, "segmap.npy"))
CX, CY = seg.mean(axis=0)
RAD = np.hypot(seg[:, 0] - CX, seg[:, 1] - CY).max()   # normalize by outer radius
UV = np.stack([(seg[:, 0] - CX) / RAD, (seg[:, 1] - CY) / RAD], axis=1)
THETA = np.arctan2(UV[:, 1], UV[:, 0])                 # segment angles
R_NORM = np.hypot(UV[:, 0], UV[:, 1])                  # 0..1 normalized radius

BRI = 90


class Drawer:
    def __init__(self):
        self.s = tpap_proto.Tapap(
            host=os.environ["TPAP_HOST"], username=os.environ["TPAP_USER"],
            password=os.environ["TPAP_PASS"], port=80, tls=False)
        self.s.discover()
        self.s.authenticate()

    def push(self, states, wait=0.6):
        self.s.send("apply_segment_effect_rule", {
            "brightness": 100, "custom": 1, "deviceType": "strip",
            "display_colors": states[:4], "enable": 1, "id": EFFECT_ID,
            "name": "draw", "segments": list(range(SEG)),
            "states": states, "type": "none"})
        time.sleep(wait)

    def photo(self, name, quality=92):
        p = os.path.join(FR, name)
        for attempt in range(5):
            subprocess.run(CAM + f" {p}", shell=True, capture_output=True)
            if os.path.exists(p) and os.path.getsize(p) > 20000:
                return p
            time.sleep(0.6)
        return None

    def off(self, wait=0.6):
        self.push([[0, 0, 0, 0]] * SEG, wait=wait)


# ---------------------------------------------------------------- shapes
def heart(u, v, scale=0.88):
    """Classic filled heart, tip at bottom. v is image-down."""
    x = u / scale
    y = -v / scale
    return (x * x + y * y - 1) ** 3 - (x * x) * (y ** 3) <= 0


def _polyline_pts(pts, n=200):
    out = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        for t in np.linspace(0, 1, n, endpoint=False):
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return np.array(out)


def _dist_to(curve, uv):
    d = np.hypot(uv[:, None, 0] - curve[None, :, 0],
                 uv[:, None, 1] - curve[None, :, 1])
    return d.min(axis=1)


def star_curve():
    pts = []
    for i in range(10):
        ang = math.pi / 2 + i * math.pi / 5
        r = 0.95 if i % 2 == 0 else 0.42
        pts.append((r * math.cos(ang), -r * math.sin(ang)))  # v-down
    return _polyline_pts(pts)


def smiley_curves():
    parts = []
    # face circle r=0.82
    t = np.linspace(0, 2 * math.pi, 300)
    parts.append(np.stack([0.82 * np.cos(t), 0.82 * np.sin(t)], axis=1))
    # smile arc: center (0, 0.05), r 0.5, lower half
    t = np.linspace(math.radians(35), math.radians(145), 80)
    parts.append(np.stack([0.5 * np.cos(t), 0.05 + 0.5 * np.sin(t)], axis=1))
    # eyes (small circles)
    for ex in (-0.34, 0.34):
        t = np.linspace(0, 2 * math.pi, 40)
        parts.append(np.stack([ex + 0.11 * np.cos(t), -0.28 + 0.11 * np.sin(t)], axis=1))
    return np.vstack(parts)


BOLT = np.array([(0.18, -0.92), (-0.28, 0.06), (-0.02, 0.06),
                 (-0.18, 0.92), (0.30, -0.12), (0.04, -0.12)])


def states_fill(mask, hue, bri=BRI):
    return [[hue, 100, bri, 0] if m else [0, 0, 0, 0] for m in mask]


def states_stroke(curve, tol, hue, bri=BRI):
    return states_fill(_dist_to(curve, UV) < tol, hue, bri)


def _ang_diff(a, b):
    d = (a - b + math.pi) % (2 * math.pi) - math.pi
    return abs(d)


def states_spokes(n=4, width=0.28, hue=190, bri=BRI, rmin=0.05):
    """n bright radial lines from the center (reads like a compass/starburst)."""
    states = [[0, 0, 0, 0]] * SEG
    for k in range(SEG):
        if R_NORM[k] < rmin:
            continue
        if min(_ang_diff(THETA[k], i * 2 * math.pi / n - math.pi / 2)
               for i in range(n)) < width:
            states[k] = [hue, 100, bri, 0]
    return states


def states_target(hue=190):
    """Outer dotted ring + mid band + bright center hub."""
    states = [[0, 0, 0, 0]] * SEG
    for k in range(SEG):
        r = R_NORM[k]
        if r > 0.78:
            states[k] = [hue, 95, BRI, 0]
        elif 0.48 < r < 0.70:
            states[k] = [hue, 95, 55, 0]
        elif r < 0.18:
            states[k] = [hue, 95, BRI, 0]
    return states


def states_pacman(mouth=0.55, face=0.0, hue=48):
    """Pac-Man: bright body, dark wedge mouth facing `face` (rad), dark eyes."""
    states = [[0, 0, 0, 0]] * SEG
    for k in range(SEG):
        if R_NORM[k] < 0.18:
            continue
        if _ang_diff(THETA[k], face) < mouth:
            continue
        states[k] = [hue, 100, BRI, 0]
    for ek in range(SEG):
        if 0.35 < R_NORM[ek] < 0.8 and min(
                _ang_diff(THETA[ek], face + 0.75),
                _ang_diff(THETA[ek], face - 0.75)) < 0.16:
            states[ek] = [0, 0, 0, 0]
    return states


SHAPES = {
    "heart":  lambda d: states_fill(heart(UV[:, 0], UV[:, 1]), 320),
    "star":   lambda d: states_stroke(star_curve(), 0.10, 48),
    "smiley": lambda d: states_stroke(smiley_curves(), 0.10, 110),
    "bolt":   lambda d: states_stroke(_polyline_pts(list(BOLT)), 0.10, 190),
    "spokes": lambda d: states_spokes(4),
    "target": lambda d: states_target(),
    "pacman": lambda d: states_pacman(0.55),
}


# ------------------------------------------------------------- animations
def anim_snake(f):
    """Rainbow comet chasing the strip order (spirals inward, ~15 turns)."""
    states = [[0, 0, 0, 0]] * SEG
    for i in range(14):
        k = (f - i) % SEG
        states[k] = [(i * 24) % 360, 100, int(BRI * (1 - i / 14)), 0]
    return states


def anim_radar(f):
    """Narrow beam sweeping around the coil center (green)."""
    a = f / 48 * 2 * math.pi
    inten = 0.5 + 0.5 * np.cos(THETA - a)
    states = [[110, 90, int(BRI * inten ** 4), 0] for inten in inten]
    return states


def anim_twinkle(f):
    """Random starfield shimmer."""
    rng = np.random.default_rng(f * 7919)
    on = set(rng.choice(SEG, 10, replace=False).tolist())
    states = [[rng.integers(0, 360), 100, int(rng.integers(30, BRI)), 0]
              if k in on else [0, 0, 0, 0] for k in range(SEG)]
    return states


def anim_pacman(f):
    """Pac-Man with a chomping mouth (oscillates open/closed)."""
    mouth = 0.25 + 0.5 * (0.5 - 0.5 * math.cos(f / 48 * 4 * math.pi))
    return states_pacman(mouth=mouth)


def anim_planet(f, r_orbit=0.55):
    """A bright planet (with fading trail) orbiting at mid radius."""
    states = [[0, 0, 10, 0]] * SEG  # dim floor for contrast
    a = f / 48 * 2 * math.pi
    scored = sorted((abs(R_NORM[k] - r_orbit) * 0.6 +
                     _ang_diff(THETA[k], a) * 0.5, k) for k in range(SEG))
    for i, (d, k) in enumerate(scored[:4]):
        if d < 0.5:
            states[k] = [200, 100, int(BRI * (1 - i * 0.22)), 0]
    return states


def anim_clock(f):
    """Coil clock: minute hand sweeps 360deg over the 48-frame cycle (60x
    speed for the demo); hour hand sits at real time; bright center hub."""
    now = time.localtime()
    a_h = ((now.tm_hour % 12) + now.tm_min / 60) / 12 * 2 * math.pi
    a_m = f / 48 * 2 * math.pi
    states = [[0, 0, 12, 0]] * SEG
    for k in range(SEG):
        r = R_NORM[k]
        if r < 0.16:
            states[k] = [0, 0, BRI, 0]
            continue
        if _ang_diff(THETA[k], a_m - math.pi / 2) < 0.16 and r > 0.2:
            states[k] = [120, 100, BRI, 0]
        elif _ang_diff(THETA[k], a_h - math.pi / 2) < 0.16 and r < 0.6:
            states[k] = [190, 100, 70, 0]
    return states


ANIMS = {"snake": anim_snake, "radar": anim_radar, "twinkle": anim_twinkle,
         "pacman": anim_pacman, "planet": anim_planet, "clock": anim_clock}
ANIM_STEPS = {"snake": 50, "radar": 48, "twinkle": 40, "pacman": 48,
              "planet": 48, "clock": 48}


def run_gif(d, name, samples=12):
    fn = ANIMS[name]
    steps = ANIM_STEPS[name]
    frames = []
    for i in range(samples):
        f = int(i * steps / samples)
        d.push(fn(f), wait=0.4)
        p = d.photo(f"gif_{name}_{i:02d}.jpg", quality=80)
        if p:
            frames.append(Image.open(p))
    if not frames:
        return None
    g = os.path.join(FR, f"gif_{name}.gif")
    frames[0].save(g, save_all=True, append_images=frames[1:],
                   duration=110, loop=0)
    return g


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "static"
    d = Drawer()
    if cmd == "off":
        d.off()
        print("off")
        return
    if cmd == "show":
        name = sys.argv[2]
        d.push(SHAPES[name](d))
        print(f"showing {name}")
        return
    if cmd == "static":
        for name in ("heart", "star", "smiley", "bolt"):
            d.push(SHAPES[name](d))
            p = d.photo(f"demo_{name}.jpg")
            print(f"{name}: {p}", flush=True)
        return
    if cmd == "anim":
        g = run_gif(d, sys.argv[2])
        print("gif:", g)
        return
    print(__doc__)


if __name__ == "__main__":
    main()
