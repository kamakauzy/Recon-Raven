# Automation Scripts — SIGINT Field Kit

Headless Python scripts for unattended signal collection and analysis. Each script maps to a phase of the F3EAD intelligence cycle and is designed to chain with others.

**Requires:** RTL-SDR dongle, GNU Radio + gr-osmosdr (for squelch_recorder & burst_detector), rtl_power (for power_logger & signal_alerter)

---

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         F3EAD SIGINT Pipeline                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  FIND        squelch_recorder.py ─── IQ captures (.cf32)                │
│              burst_detector.py ────── burst log (CSV)                    │
│              power_logger.py ──────── power heatmap (CSV)               │
│              signal_alerter.py ────── threshold alerts (CSV)            │
│                                           │                             │
│  FIX         burst_detector.py ────── pattern-of-life timing            │
│              signal_alerter.py ────── frequency watch                    │
│                                           │                             │
│  ANALYZE     baseline_diff.py ─────── new/missing/changed signals       │
│                                           │                             │
│  DISSEMINATE intel_packager.py ────── one-page intel summary (.md)      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## squelch_recorder.py — Squelch-Triggered IQ Recorder

Monitors a frequency and automatically records IQ samples to timestamped `.cf32` files when signal power exceeds the squelch threshold. Walk away, come back to captures.

**Dependencies:** GNU Radio, gr-osmosdr, RTL-SDR

```bash
# Basic — ISM 433 MHz, default squelch
./squelch_recorder.py

# VHF voice, tighter squelch
./squelch_recorder.py -f 146.52 -s -35

# LoRa band, custom output directory
./squelch_recorder.py -f 915 -s -50 -o /tmp/captures

# Headless LP/OP deployment
./squelch_recorder.py -f 433.92 --headless
```

| Flag | Default | Description |
|------|---------|-------------|
| `-f` | 433.92 | Center frequency (MHz) |
| `-s` | -40 | Squelch threshold (dB) |
| `-g` | 38 | RF gain |
| `-r` | 2.4 | Sample rate (Msps) |
| `-o` | ~/SIGINT/recordings | Output directory |
| `--min` | 1.0 | Minimum capture duration (s) — shorter = noise, deleted |
| `--max` | 300 | Max capture before file split (s) |
| `--headless` | off | No GUI, pure console output |

**Output:** `capture_<freq>MHz_<timestamp>_<rate>sps.cf32`

Open captures in URH, inspectrum, or GNU Radio for protocol analysis.

---

## burst_detector.py — Burst Detector

Detects short RF bursts (LoRa packets, FSK data, sensor transmissions), timestamps them, and logs peak power + duration. Establishes pattern-of-life.

**Dependencies:** GNU Radio, gr-osmosdr, RTL-SDR

```bash
# ISM 433 MHz burst detection
./burst_detector.py -f 433.92

# LoRa band + save IQ per burst
./burst_detector.py -f 915 -s -45 --record

# Custom log file
./burst_detector.py -f 433.92 --log ~/SIGINT/logs/ism_bursts.csv

# Catch very short bursts (10ms+)
./burst_detector.py -f 462.5625 --min-burst 0.01
```

| Flag | Default | Description |
|------|---------|-------------|
| `-f` | 433.92 | Center frequency (MHz) |
| `-s` | -40 | Squelch threshold (dB) |
| `-g` | 38 | RF gain |
| `-r` | 2.4 | Sample rate (Msps) |
| `-o` | ~/SIGINT/recordings | IQ output directory |
| `--record` | off | Save IQ data for each burst |
| `--log` | ~/SIGINT/logs/bursts.csv | Append burst log to CSV |
| `--min-burst` | 0.02 | Minimum burst duration (s) |

**Output CSV columns:** `timestamp_utc, freq_mhz, duration_ms, peak_power_db, iq_file`

Feed CSV into `baseline_diff.py` or `intel_packager.py` for analysis.

---

## power_logger.py — Continuous Power Logger

Wraps `rtl_power` to produce time-series spectral data over a frequency range. Generates heatmap-ready CSV for spectrum occupancy studies and pattern-of-life.

**Dependencies:** rtl_power (part of rtl-sdr package), optionally numpy+matplotlib for heatmaps

```bash
# ISM 433 band (400-450 MHz)
./power_logger.py

# VHF band, fine resolution
./power_logger.py -l 144 -u 148 -b 25k

# LoRa band, 2 hours, generate spectrogram
./power_logger.py -l 900 -u 930 --duration 7200 --heatmap

# UHF FRS/GMRS
./power_logger.py -l 460 -u 470 -i 5
```

| Flag | Default | Description |
|------|---------|-------------|
| `-l` | 400 | Lower frequency bound (MHz) |
| `-u` | 450 | Upper frequency bound (MHz) |
| `-b` | 100k | Frequency bin size |
| `-i` | 10 | Sweep interval (seconds) |
| `-g` | 38 | RF gain |
| `-p` | 0 | PPM frequency correction |
| `-d` | 0 (infinite) | Total duration (seconds) |
| `-o` | ~/SIGINT/logs | Output directory |
| `--heatmap` | off | Generate spectrogram PNG at end |

**Output:** rtl_power-format CSV + optional `.png` heatmap

---

## signal_alerter.py — Signal Alerter

Monitors a frequency and fires multi-channel alerts when signal activity is detected. Desktop notifications, audible beeps, CSV logging, and custom command execution.

**Dependencies:** rtl_power (part of rtl-sdr package), optionally notify-send (desktop alerts)

```bash
# Alert on FRS Channel 1 activity
./signal_alerter.py -f 462.5625

# VHF voice + audible beep
./signal_alerter.py -f 146.52 -s -35 --beep

# ISM band, max 1 alert per minute
./signal_alerter.py -f 433.92 --cooldown 60

# Trigger external script on LoRa activity
./signal_alerter.py -f 915 --command "./start_recording.sh"

# Quiet mode — only print alerts
./signal_alerter.py -f 433.92 -q
```

| Flag | Default | Description |
|------|---------|-------------|
| `-f` | (required) | Target frequency (MHz) |
| `-s` | -40 | Alert threshold (dB) |
| `-g` | 38 | RF gain |
| `-i` | 5 | Scan interval (seconds) |
| `--cooldown` | 30 | Min seconds between alerts |
| `--beep` | off | Play audible alert sound |
| `--command` | none | Shell command on alert (gets env vars) |
| `--log` | ~/SIGINT/logs/alerts.csv | Alert log path |
| `-q` | off | Quiet — suppress routine scan output |

**Custom command environment variables:**
- `ALERT_FREQ` — frequency in MHz
- `ALERT_POWER` — detected power in dB
- `ALERT_NUM` — sequential alert number
- `ALERT_TIME` — UTC timestamp

**Output CSV columns:** `timestamp_utc, freq_mhz, power_db, threshold_db, alert_num`

---

## baseline_diff.py — Baseline Diff

Compares two `rtl_433` CSV baselines and reports changes: new signals, disappeared signals, power level shifts, and repetition rate changes.

**Dependencies:** Python 3 (stdlib only, no external packages)

```bash
# Compare two baselines
./baseline_diff.py baselines/day1.csv baselines/day2.csv

# Custom power threshold
./baseline_diff.py old.csv new.csv --threshold 5

# Save report to file
./baseline_diff.py old.csv new.csv -o ~/SIGINT/logs/diff_report.txt
```

| Flag | Default | Description |
|------|---------|-------------|
| (positional 1) | (required) | Old/reference baseline CSV |
| (positional 2) | (required) | New baseline CSV to compare |
| `-t` | 6 | Power change threshold (dB) |
| `-o` | stdout | Write report to file |

**Anomaly types reported:**
- **NEW SIGNALS** — Not in old baseline. Potential threat. Investigate.
- **DISAPPEARED** — Was present, now gone. Source moved or powered off.
- **POWER CHANGES** — Same source, significant strength change.
- **RATE CHANGES** — Same source, transmitting more/less often.

Generate baselines with: `rtl_433 -f 433.92M -R all -F csv:baseline.csv`

---

## intel_packager.py — Intel Packager

Ingests all collection logs and produces a formatted one-page markdown intelligence summary. The final F3EAD DISSEMINATE step.

**Dependencies:** Python 3 (stdlib only)

```bash
# From burst data
./intel_packager.py --bursts ~/SIGINT/logs/bursts.csv

# Full data stack
./intel_packager.py --bursts bursts.csv --alerts alerts.csv --bearings df.csv -o report.md

# Auto-discover all logs in a directory
./intel_packager.py --all ~/SIGINT/logs/ --title "OP WATCHDOG" --location "Grid EN82"

# Include baseline diff
./intel_packager.py --bursts b.csv --baseline-diff diff.txt -o intel.md
```

| Flag | Default | Description |
|------|---------|-------------|
| `--bursts` | none | Burst detector CSV |
| `--alerts` | none | Signal alerter CSV |
| `--bearings` | none | DF bearings CSV (timestamp,freq,bearing_deg,confidence) |
| `--baseline-diff` | none | baseline_diff.py text report |
| `--all` | none | Auto-discover all logs in directory |
| `-o` | stdout | Output file path |
| `--title` | none | Operation name for header |
| `--location` | none | Collection location |

**Report sections:**
1. Executive Summary (total events, top frequencies, time span)
2. Burst Activity (per-frequency stats, hourly pattern-of-life)
3. Threshold Alerts (table of last 20)
4. DF Bearings + triangulation candidates
5. Baseline Comparison (embedded diff)
6. Analyst Recommendations (auto-generated action items)

---

## Chaining Examples

```bash
# Full unattended collection session
./burst_detector.py -f 433.92 --record --log ~/SIGINT/logs/bursts.csv &
./signal_alerter.py -f 433.92 -q --cooldown 60 &
./power_logger.py -l 430 -u 440 --duration 3600 &
wait

# After collection — analyze and report
./baseline_diff.py baselines/before.csv baselines/after.csv -o ~/SIGINT/logs/diff.txt
./intel_packager.py --all ~/SIGINT/logs/ --title "Night Watch" -o ~/SIGINT/intel-packages/report.md
```

```bash
# Alert triggers recording on activity
./signal_alerter.py -f 462.5625 --command "python3 scripts/squelch_recorder.py -f 462.5625 --max 30"
```

---

## Output File Locations

All scripts default to the `~/SIGINT/` working directory:

```
~/SIGINT/
├── recordings/    ← squelch_recorder.py, burst_detector.py IQ files
├── logs/          ← burst CSVs, alert CSVs, power logger data
│   ├── bursts.csv
│   ├── alerts.csv
│   └── power_*.csv
├── baselines/     ← rtl_433 baseline CSVs for diff comparison
└── intel-packages/ ← intel_packager.py reports
```
