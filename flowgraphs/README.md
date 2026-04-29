# GNU Radio Flow Graphs — SIGINT Field Kit

Tactical `.grc` flow graphs for passive RF monitoring. Open in GNU Radio Companion or run as Python scripts. All receive-only — no transmit capability.

**Requires:** GNU Radio 3.10.x, gr-osmosdr, RTL-SDR dongle(s) connected via USB.

---

## Quick Reference

| File | Purpose | Dongles | Default Freq | F3EAD Phase |
|------|---------|---------|-------------|-------------|
| `fm_monitor.grc` | Wideband FM voice receiver | 1 | 146.52 MHz | FIND |
| `ism_scanner_433.grc` | ISM 433 MHz passive scanner | 1 | 433.92 MHz | FIND |
| `lora_watcher_915.grc` | LoRa/Meshtastic band watcher | 1 | 915.0 MHz | FIND |
| `nbfm_scanner.grc` | FRS/GMRS channel scanner with audio | 1 | 465.0 MHz (center) | FIX |
| `quad_band_monitor.grc` | 4-band simultaneous monitor | 4 | VHF/ISM/UHF/LoRa | FIND |

---

## Detailed Instructions

### fm_monitor.grc — Wideband FM Voice Monitor

**Purpose:** Monitor VHF voice communications (simplex, repeater outputs, etc.) with real-time audio demodulation.

**Hardware:** 1× RTL-SDR dongle

**Default Configuration:**
- Frequency: 146.52 MHz (2m calling frequency)
- Sample rate: 2.4 Msps
- Audio output: system default device
- Demodulation: Wideband FM (200 kHz deviation)

**GUI Controls:**
| Control | Range | Description |
|---------|-------|-------------|
| Frequency (MHz) | 80–500 | Tune to target frequency |
| RF Gain | 0–49 | RTL-SDR gain (38 typical) |
| Volume | 0–1.0 | Audio output level |

**Display:** Waterfall + FFT plot showing 2.4 MHz of bandwidth around the center frequency.

**Field Use:**
```bash
# Open in GRC for GUI tuning
gnuradio-companion flowgraphs/fm_monitor.grc

# Or generate Python and run headless (after generating once in GRC)
cd flowgraphs
python3 fm_monitor.py
```

**Operational Tips:**
- Tune to 146.52 MHz for 2m simplex calling
- Common repeater outputs: 146.61–147.39 MHz (600 kHz offset pairs)
- Set gain to 30–40 in urban environments; 40–49 in rural
- Use waterfall to visually spot intermittent transmissions before tuning

---

### ism_scanner_433.grc — ISM 433 MHz Passive Scanner

**Purpose:** Monitor the 433.92 MHz ISM band for wireless sensors, weather stations, car key fobs, tire pressure monitors, and other OOK/FSK devices.

**Hardware:** 1× RTL-SDR dongle

**Default Configuration:**
- Frequency: 433.92 MHz (center of ISM band)
- Sample rate: 2.4 Msps
- Bandwidth coverage: ~432.7–435.1 MHz

**GUI Controls:**
| Control | Range | Description |
|---------|-------|-------------|
| Center Freq (MHz) | 420–450 | Shift window across ISM range |
| RF Gain | 0–49 | SDR gain |

**Display:** Waterfall + FFT. Bursts appear as bright horizontal blips on the waterfall.

**Field Use:**
```bash
gnuradio-companion flowgraphs/ism_scanner_433.grc
```

**What You'll See:**
- Weather stations: periodic 433.92 MHz OOK bursts every 30–60s
- Car key fobs: short rolling-code bursts
- Tire pressure sensors (TPMS): periodic FSK at 433.92 MHz
- Wireless doorbells, garage door openers, etc.

**Operational Tips:**
- Pair with `rtl_433` CLI for automatic protocol decoding
- Run `rtl_433 -f 433.92M -R all > baseline.csv` alongside for logging
- Bursts under 10ms are usually noise; 50–500ms are device transmissions
- Use this for environmental baseline — learn what's "normal" before looking for anomalies

---

### lora_watcher_915.grc — LoRa / Meshtastic Band Watcher

**Purpose:** Passive monitoring of the 915 MHz ISM band (US LoRa, Meshtastic, IoT devices). Visual only — no demodulation (LoRa requires specialized demod).

**Hardware:** 1× RTL-SDR dongle

**Default Configuration:**
- Frequency: 915.0 MHz (center of US ISM)
- Sample rate: 2.4 Msps
- Bandwidth coverage: ~913.8–916.2 MHz

**GUI Controls:**
| Control | Range | Description |
|---------|-------|-------------|
| Center Freq (MHz) | 900–930 | Shift across LoRa channels |
| RF Gain | 0–49 | SDR gain |

**Display:** Waterfall + FFT. LoRa chirps appear as distinctive diagonal lines (chirp spread spectrum) on the waterfall.

**Field Use:**
```bash
gnuradio-companion flowgraphs/lora_watcher_915.grc
```

**What You'll See:**
- Meshtastic nodes: chirp-spread bursts across 125–500 kHz channels
- LoRaWAN gateways/sensors: regular uplink chirps
- Smart meters and agricultural IoT

**Operational Tips:**
- LoRa uses channels: 903.9, 904.1, 904.3... 905.3 MHz (US915 uplink)
- Meshtastic default: 906.875 MHz (US LongFast)
- Chirps are unmistakable on waterfall — diagonal bright lines
- Count burst frequency to establish pattern-of-life (how many nodes active?)
- Combine with `scripts/burst_detector.py -f 915` for automated logging

---

### nbfm_scanner.grc — NBFM Voice Channel Scanner

**Purpose:** Monitor FRS, GMRS, and MURS voice channels with a single RTL-SDR. Includes channel selector, squelch, NBFM demodulation, and audio output. Stops on active channels.

**Hardware:** 1× RTL-SDR dongle (single wideband capture covers all FRS/GMRS)

**Default Configuration:**
- Center frequency: 465.0 MHz (covers FRS 462–467 MHz)
- Sample rate: 2.4 Msps (enough for entire FRS/GMRS allocation)
- Demodulation: Narrowband FM (5 kHz deviation)
- Squelch: power-based, adjustable

**Preset Channels:**
| # | Label | Frequency |
|---|-------|-----------|
| 0 | FRS 1 | 462.5625 MHz |
| 1 | FRS 2 | 462.5875 MHz |
| 2 | FRS 3 | 462.6125 MHz |
| 3 | FRS 4 | 462.6375 MHz |
| 4 | FRS 5 | 462.6625 MHz |
| 5 | FRS 6 | 462.6875 MHz |
| 6 | FRS 7 | 462.7125 MHz |
| 7 | FRS 8 | 467.5625 MHz |
| 8 | GMRS 15 | 462.550 MHz |
| 9 | GMRS 16 | 462.575 MHz |

**GUI Controls:**
| Control | Range | Description |
|---------|-------|-------------|
| Channel | Dropdown (10 ch) | Select target FRS/GMRS channel |
| RF Gain | 0–49 | SDR gain |
| Squelch (dB) | -80 to 0 | Open squelch threshold |
| Volume | 0–1.0 | Audio output level |

**Display:**
- Wideband waterfall/FFT showing entire FRS/GMRS band simultaneously
- Narrowband audio scope on the demodulated channel

**Field Use:**
```bash
gnuradio-companion flowgraphs/nbfm_scanner.grc
```

**How It Works:**
1. RTL-SDR captures 2.4 MHz centered on 465 MHz
2. Wideband FFT/waterfall shows all channel activity at once
3. Select a channel from the dropdown to demodulate
4. Frequency-xlating FIR filter isolates the selected channel
5. Power squelch gates audio (no noise between transmissions)
6. NBFM demod → audio output

**Operational Tips:**
- Watch the wideband waterfall to see which channels are active
- FRS 1 (462.5625) is the most common family/hiking channel
- GMRS 15-22 are repeater-capable and used by more serious operators
- FRS channels are interleaved with GMRS — listen to both
- For scanning mode: manually flip through channels watching power levels
- Pair with `scripts/squelch_recorder.py -f 462.5625` for unattended recording

---

### quad_band_monitor.grc — Quad-Band Tactical Monitor

**Purpose:** Simultaneous monitoring of 4 tactical frequency bands with 4 RTL-SDR dongles. One-glance situational awareness across VHF, ISM, UHF, and LoRa bands. The primary SIGINT collection display.

**Hardware:** 4× RTL-SDR dongles (assigned as rtl=0 through rtl=3)

**Default Configuration:**
| Band | Dongle | Default Freq | Coverage |
|------|--------|-------------|----------|
| VHF Voice | rtl=0 | 146.52 MHz | 2m ham/simplex |
| ISM Sensors | rtl=1 | 433.92 MHz | OOK/FSK devices |
| UHF FRS/GMRS | rtl=2 | 462.00 MHz | Voice channels |
| LoRa/Meshtastic | rtl=3 | 915.00 MHz | IoT/mesh |

- Sample rate: 2.4 Msps per dongle
- Total instantaneous bandwidth: 9.6 MHz across 4 bands

**GUI Controls:**
| Control | Range | Description |
|---------|-------|-------------|
| RF Gain (all) | 0–49 | Global gain for all 4 dongles |
| VHF (MHz) | 140–174 | Band 1 center frequency |
| ISM (MHz) | 420–450 | Band 2 center frequency |
| UHF (MHz) | 450–475 | Band 3 center frequency |
| LoRa (MHz) | 900–930 | Band 4 center frequency |

**Display:** 4 stacked waterfall + FFT panels (one per band), arranged vertically. Each panel shows 2.4 MHz of instantaneous bandwidth.

**Field Use:**
```bash
gnuradio-companion flowgraphs/quad_band_monitor.grc
```

**Dongle Assignment:**
```bash
# List connected RTL-SDR dongles and their indices
rtl_test -t    # press Ctrl+C after it shows device list

# If indices aren't in order, use serial numbers instead:
# In GRC, change source args from "rtl=0" to "rtl=SERIAL"
rtl_eeprom -s 00000001    # set serial on dongle 1
rtl_eeprom -s 00000002    # set serial on dongle 2
# etc.
```

**Single-Dongle Fallback:**
If you only have 1 dongle, disable 3 of the 4 source blocks in GRC (right-click → Disable) and use the remaining band's frequency slider to hop between bands manually.

**Operational Tips:**
- Mount the 4 dongles on a powered USB hub to avoid current issues
- Use different antenna types per band for optimal reception:
  - VHF: telescoping whip extended to ~19" (quarter-wave 146 MHz)
  - ISM/UHF: short rubber duck or ground-plane (6–7")
  - LoRa: 915 MHz stub or PCB antenna
- Watch all 4 waterfalls simultaneously — correlate activity across bands
- LoRa diagonal chirps + UHF voice at the same time = someone using Meshtastic + FRS (comms team pattern)
- Feed recordings from each band into `scripts/burst_detector.py` for pattern-of-life

---

## Running Without GUI (Headless/SSH)

All flow graphs can be generated to Python and run without a display:

```bash
# Generate Python from GRC (one-time)
grcc flowgraphs/fm_monitor.grc -o flowgraphs/

# Run headless (no waterfall, but still processes/records)
# Requires modifying generate_options from qt_gui to no_gui in GRC
python3 flowgraphs/fm_monitor.py
```

For headless monitoring, use the Python scripts in `scripts/` instead:
- `scripts/squelch_recorder.py` — records IQ when signal present
- `scripts/burst_detector.py` — detects and logs short bursts
- `scripts/power_logger.py` — continuous power measurement

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "No devices found" | Check `lsusb` for RTL-SDR. Run `install.sh` to fix udev rules. Replug USB. |
| "Device or resource busy" | Another program has the dongle. Kill `rtl_test`, `gqrx`, `sdr++`, etc. |
| Waterfall is all noise | Gain too low (increase to 38+) or antenna disconnected |
| Audio crackling | Reduce sample rate to 1.2 Msps or increase audio buffer |
| "rtl=1 not found" (quad) | Only 1 dongle connected. Disable unused source blocks. |
| GRC won't open file | Version mismatch. Needs GNU Radio 3.10.x (DragonOS ships this). |
| Frequency drift | RTL-SDRs drift with temperature. Let warm up 5 min or set ppm correction. |

---

## Integration with Scripts

These flow graphs are the visual/real-time component. For automated, unattended collection, use the Python scripts in `scripts/`:

```
┌─────────────────────────────────────────────────────────────────┐
│  MANNED (GUI)              │  UNATTENDED (headless)             │
├────────────────────────────┼────────────────────────────────────┤
│  fm_monitor.grc            │  squelch_recorder.py -f 146.52     │
│  ism_scanner_433.grc       │  burst_detector.py -f 433.92       │
│  lora_watcher_915.grc      │  burst_detector.py -f 915          │
│  nbfm_scanner.grc          │  squelch_recorder.py -f 462.5625   │
│  quad_band_monitor.grc     │  power_logger.py -l 140 -u 920     │
└────────────────────────────┴────────────────────────────────────┘
```

---

## Notes

- All flow graphs are **receive-only** (passive monitoring)
- Frequency, gain, and volume sliders are adjustable at runtime via the GUI
- Waterfall and FFT displays update in real-time
- Tested with GNU Radio 3.10.x on DragonOS Focal/FocalX
- All files are Unlicensed — modify freely for your operational needs
