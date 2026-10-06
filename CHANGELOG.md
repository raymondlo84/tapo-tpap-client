# Changelog

Project history for `tapo-tpap-client` (newest first). For the build
environment this was developed on, see [SETUP.md](SETUP.md); for usage,
see [README.md](README.md).

- **2026-10-06**: fixed disappearing clock hands. Two geometry bugs, not
  rounding: (1) `nearest()` had a 25.8deg distance cutoff, but the spiral
  windings have angular gaps up to 109deg in the outer ring, so the second
  hand fell into a dead zone and vanished ~17% of the day; (2) the hand
  bands overlap, so when two hands targeted the same LED the write order
  (hour then minute then second) let the dim second clobber the bright
  minute. Fix: no distance cutoff (a hand is at worst ~22deg off, never
  missing), the second band widened to R>0.58 (21 LEDs, 44deg max gap),
  and collision-aware placement - each hand takes the nearest *free* LED
  (minute first, then second, then hour), so all three stay visible even
  at :00. Verified: full-day simulation, 0 missing hands, 0 collisions.

- **2026-10-05**: re-oriented the coil (now propped face-on like a clock
  dial) and re-aligned: re-ran `calibrate_markers.py` (44/50 points; the
  disc-masking heuristic was dropped because a bright window behind the
  coil defeated it - the cyan marker's high saturation is the robust
  filter), added `align_clock.py` which reads the hand-written 12/6 marks
  to set the clock face orientation (`clock_ref.npy`), and made
  `coil_clock.py`/`draw.py` tolerate missed (NaN) calibration points.

- **2026-10-05**: added `coil/coil_clock.py` — a persistent real-time clock on
  the coil (hub + blue hour hand + green minute hand + amber second marker,
  push-on-change pacing, re-auth on error), verified live against the wall
  clock and running as `coil-clock.service` (systemd user service).

- **2026-10-05**: added `coil/` — webcam-driven constellation demos for a
  coil-wound L930. `calibrate_markers.py` maps all 50 segments to pixel
  positions (single-cyan-marker + webcam, verified 50/50); `draw.py` rasterizes
  shapes in image space and lights the segments that fall inside. Seven static
  patterns (heart, star, smiley, bolt, spokes, target, pac-man) and five
  animations (snake, radar, twinkle, planet, clock), each verified by photo/GIF
  in `coil/media/`.

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
