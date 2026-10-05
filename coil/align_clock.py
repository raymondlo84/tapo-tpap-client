#!/usr/bin/env python3
"""Detect the physical 12-o'clock direction on the coil and store it.

The user hand-writes "12" and "6" on the coil so the clock face can be
aligned to the physical orientation. This script:
  1. Takes a DARK photo (all LEDs off) so the white diffuser disc + blue
     ink marks are cleanly visible (no LED glare).
  2. Finds the blue ink marks and splits them into top/bottom halves.
  3. Because the 12 and 6 marks sit on a diameter (verified: ~180deg apart),
     the disc center is the midpoint of the two mark centroids, and the
     12-o'clock image-angle is the angle from that center to the "12" mark.
     (No disc detection needed - a bright window behind the coil would
     fool a disc-based center estimate.)
  4. Saves that angle (radians) to coil/clock_ref.npy. coil_clock.py reads
     it as the 12-o'clock reference instead of assuming "straight up".

Run after any re-orientation:
    python coil/align_clock.py
"""
import math
import os
import subprocess
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import coil_clock as cc  # reuse connect() + credentials

# Generous box around the coil in the current webcam view (tune if the
# camera moves). x0,y0,x1,y1
BOX = (400, 110, 870, 670)
CAM = "fswebcam -d /dev/video0 -r 1280x720 -S --no-banner"


def hsv(arr):
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    d = mx - mn
    v = mx
    s = np.where(mx > 0, d / mx, 0.0)
    h = np.zeros_like(v)
    m = (mx == r) & (d > 0); h[m] = (60 * ((g[m] - b[m]) / d[m])) % 360
    m = (mx == g) & (d > 0); h[m] = 60 * ((b[m] - r[m]) / d[m] + 2)
    m = (mx == b) & (d > 0); h[m] = 60 * ((r[m] - g[m]) / d[m] + 4)
    return h, s, v


def snap_all_off():
    """Push all-off, then grab a dark webcam frame."""
    s = cc.connect()
    s.send("apply_segment_effect_rule", {
        "brightness": 100, "custom": 1, "deviceType": "strip",
        "display_colors": [[0, 0, 0, 0]], "enable": 1,
        "id": "TapoStrip_calib", "name": "off",
        "segments": [49], "states": [[0, 0, 0, 0]], "type": "none"})
    time.sleep(0.8)
    p = os.path.join(HERE, "frames", "align_off.jpg")
    os.makedirs(os.path.join(HERE, "frames"), exist_ok=True)
    for _ in range(6):
        subprocess.run(CAM + " " + p, shell=True, capture_output=True)
        if os.path.exists(p) and os.path.getsize(p) > 20000:
            return p
        time.sleep(0.6)
    raise RuntimeError("camera failed to produce a frame")


def main():
    p = sys.argv[1] if len(sys.argv) > 1 else snap_all_off()
    im = np.asarray(Image.open(p).convert("RGB"), dtype=np.float32) / 255.0
    h, s, v = hsv(im)
    x0, y0, x1, y1 = BOX

    # --- ink marks: blue pen, darker than the bright diffuser ---
    ink = (v < 0.45) & (s > 0.08) & (h > 140) & (h < 300)
    ink[:y0, :] = ink[y1:, :] = ink[:, :x0] = ink[:, x1:] = False
    iy, ix = np.where(ink)
    if len(ix) < 40:
        raise RuntimeError(
            "not enough ink found - check the 12/6 marks are visible")
    # split into two marks: one is above the other. Use a robust split:
    # cluster by y (the marks are vertically separated on the dial)
    ys_sorted = np.sort(np.unique(iy))
    gap_idx = np.argmax(np.diff(ys_sorted))
    split_y = (ys_sorted[gap_idx] + ys_sorted[gap_idx + 1]) / 2.0
    top, bot = iy < split_y, iy >= split_y
    if top.sum() < 15 or bot.sum() < 15:
        raise RuntimeError(
            f"could not split into two marks (top={top.sum()}, "
            f"bottom={bot.sum()}) - is both 12 and 6 visible?")
    m12 = (float(ix[top].mean()), float(iy[top].mean()))
    m6 = (float(ix[bot].mean()), float(iy[bot].mean()))
    # The 12 and 6 marks define a diameter of the clock face, so the disc
    # center is their MIDPOINT and the 12 direction is the vector from that
    # center to the "12" mark. (Do NOT average the two angles: when they are
    # ~180 apart, the angular mean is numerically unstable and can flip to
    # the wrong hemisphere. The marks are also slightly tilted in perspective
    # - the reel leans - so the separation measures <180, which is expected.)
    cx, cy = (m12[0] + m6[0]) / 2.0, (m12[1] + m6[1]) / 2.0
    a12 = math.atan2(m12[1] - cy, m12[0] - cx)
    a6 = math.atan2(m6[1] - cy, m6[0] - cx)
    sep = abs((a12 - a6 + math.pi) % (2 * math.pi) - math.pi)
    print(f"12 mark at ({m12[0]:.0f},{m12[1]:.0f}), "
          f"6 mark at ({m6[0]:.0f},{m6[1]:.0f})")
    print(f"disc center (midpoint of marks): ({cx:.0f},{cy:.0f})")
    print(f"12 @ {math.degrees(a12):.1f}deg, 6 @ {math.degrees(a6):.1f}deg "
          f"(separation {math.degrees(sep):.1f}deg; <180 is fine when the "
          f"reel leans toward the camera)")
    if sep < 140:
        print("WARNING: marks are NOT nearly diametrically opposite - check "
              "that both marks are fully in frame and not cut off", file=sys.stderr)
    a12 = (a12 + math.pi) % (2 * math.pi) - math.pi
    print(f"=> 12-o'clock image angle A12 = {a12:.4f} rad "
          f"({math.degrees(a12):.1f}deg)")

    ref = os.path.join(HERE, "clock_ref.npy")
    np.save(ref, np.array([a12, cx, cy]))
    print(f"wrote {ref}  [A12, center_x, center_y]")


if __name__ == "__main__":
    main()
