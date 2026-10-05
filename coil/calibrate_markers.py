#!/usr/bin/env python3
"""Single-marker calibration: for each of the 50 segments, light ONLY that
segment bright cyan (all others brightness 0), snap a webcam photo, and take
the bright cyan blob's centroid as the segment's (x,y).

Why single-marker (not hue-binning the full rainbow): the box walls glow
red from the strip, so hue bins get poisoned by box glow / the white cable.
A unique bright cyan marker vs a dark coil is unambiguous and needs no
model assumption about the coil shape.

Output: segmap.npy (50x2 float32, image pixels) + frames/segmap_overlay.jpg.
"""
import os
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(HERE, "frames")
os.makedirs(FR, exist_ok=True)
sys.path.insert(0, os.path.dirname(HERE))  # repo root holds tpap_proto
import tpap_proto  # noqa: E402

# NOTE: CAM device + ROI (box interior in 1280x720) are tuned to the original
# webcam angle; adjust both for your own setup.

SEG = 50
CAM = "fswebcam -d /dev/video0 -r 1280x720 -S --no-banner"
ROI = (470, 110, 890, 545)      # x0,y0,x1,y1 box interior margin
MARKER = [180, 100, 100, 0]    # cyan: hue far from the red box glow
EFFECT_ID = "TapoStrip_calib"


def _hsv(arr):
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    d = mx - mn
    v = mx
    s = np.where(mx > 0, d / mx, 0.0)
    h = np.zeros_like(v)
    m = (mx == r) & (d > 0)
    h[m] = (60 * ((g[m] - b[m]) / d[m])) % 360
    m = (mx == g) & (d > 0)
    h[m] = 60 * ((b[m] - r[m]) / d[m] + 2)
    m = (mx == b) & (d > 0)
    h[m] = 60 * ((r[m] - g[m]) / d[m] + 4)
    return h, s, v


def extract_marker(path):
    im = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
    h, s, v = _hsv(im)
    x0, y0, x1, y1 = ROI
    m = (h >= 150) & (h <= 215) & (s > 0.45) & (v > 0.40)
    m[:y0, :] = False
    m[y1:, :] = False
    m[:, :x0] = False
    m[:, x1:] = False
    ys, xs = np.where(m)
    if xs.size < 30:
        return None
    w = v[ys, xs] ** 2
    return float(np.sum(xs * w) / np.sum(w)), float(np.sum(ys * w) / np.sum(w)), int(xs.size)


def snap(p):
    """Capture one frame, retrying on camera busy/short-frame (device race)."""
    for attempt in range(6):
        r = subprocess.run(CAM + f" {p}", shell=True,
                           capture_output=True, text=True)
        if os.path.exists(p) and os.path.getsize(p) > 20000:
            return True
        time.sleep(0.6)  # let the previous grabber release the device
    return False


def main():
    s = tpap_proto.Tapap(
        host=os.environ["TPAP_HOST"], username=os.environ["TPAP_USER"],
        password=os.environ["TPAP_PASS"], port=80, tls=False)
    s.discover()
    s.authenticate()
    print("AUTH OK", flush=True)

    ends = list(range(SEG))
    pts = {}
    t0 = time.time()
    for k in range(SEG):
        states = [[0, 0, 0, 0]] * SEG
        states[k] = list(MARKER)
        s.send("apply_segment_effect_rule", {
            "brightness": 100, "custom": 1, "deviceType": "strip",
            "display_colors": states[:4], "enable": 1, "id": EFFECT_ID,
            "name": "marker", "segments": ends, "states": states,
            "type": "none",
        })
        time.sleep(0.7)  # device apply + LED ramp + camera settle
        p = os.path.join(FR, f"mk_{k:02d}.jpg")
        if not snap(p):
            print(f"seg {k:2d}: CAMERA FAIL", flush=True)
            pts[k] = None
        else:
            r = extract_marker(p)
            if r is None:  # marker not found -> one more shot
                time.sleep(0.5)
                if snap(p):
                    r = extract_marker(p)
            pts[k] = r
        tag = f"({r[0]:5.0f},{r[1]:5.0f}) n={r[2]:5d}" if r else "MISS"
        print(f"seg {k:2d}: {tag}", flush=True)

    seg = np.full((SEG, 2), np.nan)
    for k, r in pts.items():
        if r:
            seg[k] = r[:2]
    np.save(os.path.join(HERE, "segmap.npy"), seg)
    ok = int(np.sum(~np.isnan(seg[:, 0])))
    print(f"\nDONE {ok}/{SEG} in {time.time()-t0:.0f}s", flush=True)

    # overlay on the last frame (all off -> shows coil silhouette + markers)
    base = Image.open(os.path.join(FR, f"mk_{SEG-1:02d}.jpg")).convert("RGB")
    dr = ImageDraw.Draw(base)
    for k in range(SEG):
        x, y = seg[k]
        if np.isnan(x):
            continue
        dr.ellipse((x-6, y-6, x+6, y+6), outline=(0, 255, 255), width=2)
        dr.text((x+7, y-9), str(k), fill=(255, 255, 255))
    # trace the strip order so continuity is visible
    pts_ok = [(seg[k, 0], seg[k, 1]) for k in range(SEG) if not np.isnan(seg[k, 0])]
    if len(pts_ok) > 1:
        dr.line(pts_ok, fill=(255, 255, 0), width=2)
    base.save(os.path.join(FR, "segmap_overlay.jpg"), quality=92)
    print("wrote", os.path.join(FR, "segmap_overlay.jpg"), flush=True)


if __name__ == "__main__":
    main()
