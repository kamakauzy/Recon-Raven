# Direction Finding (DF) Cheatsheet

Techniques for locating signal sources using portable COTS equipment.

---

## Body-Block / Null Method
1. Use a handheld radio or SDR with omnidirectional antenna
2. Hold device against your chest
3. Slowly rotate 360°
4. **Null zone** (signal drop / minimum) = signal is behind you
5. Mark bearing with compass
6. Move 50+ meters and repeat for second bearing

**Best for:** Quick bearings with minimal gear, works with any receiver.

## Yagi Sweep
1. Use a directional antenna (Yagi, log-periodic)
2. Point antenna and slowly sweep in ~30° increments
3. **Peak signal strength** = signal direction
4. Record bearing and signal strength at each position
5. Repeat from a second location

**Best for:** Longer-range signals, better accuracy than body-block.

## Cross-Bearing Triangulation
1. Take bearings from **3+ separate locations** (minimum 2, but 3 mitigates urban multipath)
2. Plot bearing lines on a map
3. Where lines intersect = probable source location
4. Adjust confidence based on terrain — urban canyons and buildings cause reflections

**Best for:** Fixing an emitter location with confidence.

## KrakenSDR / Multi-Antenna
1. Deploy coherent multi-antenna array
2. Run DOA (direction of arrival) software
3. Log bearing + confidence automatically
4. Drive or move for multiple readings to triangulate

**Best for:** High-accuracy automated DF, vehicle-mounted operations.

---

## Common DF Mistakes
- Standing near metal, concrete, or vehicles (distorts signal)
- Wrong antenna polarization (vertical vs. horizontal — can lose 20+ dB)
- Trusting a single bearing in urban terrain (multipath reflections)
- Misreading signal spikes caused by reflections as primary source

## Rule of Thumb
> Even an imprecise bearing is useful when combined with pattern-of-life data and multiple observations.
