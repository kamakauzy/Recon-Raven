# Integration Guide

How Recon-Raven interacts with external tools on DragonOS.

---

## rtl_433

**Used by:** Scheduler (baseline captures), Signal Alerter

Raven invokes `rtl_433` as a subprocess for baseline spectrum captures. The scheduler
runs it on a cron (default: every 6 hours) and exports CSV for diff analysis.

```
rtl_433 -f 433.92M -f 315M -d 0 -F csv:/var/lib/recon-raven/baselines/baseline_20260429.csv -T 120
```

**Prerequisites:**
- `rtl_433` installed and in PATH (included in DragonOS)
- At least one RTL-SDR connected

**Configuration:**
```yaml
scheduler:
  baseline_cron: "0 */6 * * *"
  baseline_duration: 120
  baseline_frequencies:
    - 433.92
    - 315.0
```

**Custom decoders:** Place custom rtl_433 config files in `/etc/rtl_433/` — Raven
passes through whatever rtl_433 detects.

---

## rtl_power

**Used by:** Signal Alerter engine (`engine/signal_alerter.py`)

Performs wideband power sweeps for threshold-based alerting. Raven monitors output
for power levels exceeding a configurable threshold and fires alert events.

```
rtl_power -f 400M:500M:100k -d 0 -g 38 -i 1 -1
```

**Prerequisites:**
- `rtl-sdr` package installed (included in DragonOS)
- `rtl_power` in PATH

---

## GNU Radio + osmosdr

**Used by:** Burst Detector, Squelch Recorder, Power Logger engines

Engine scripts use GNU Radio with the `osmosdr` source block to access RTL-SDR
hardware. They run as subprocesses under the **system Python** (`/usr/bin/python3`),
not the Raven venv, because GNU Radio and gr-osmosdr are system-installed packages.

**Prerequisites:**
- GNU Radio 3.10+ with `gr-osmosdr` (included in DragonOS)
- System python3 must have `gnuradio`, `osmosdr` importable

**Why system Python?** GNU Radio's Python bindings are compiled against the system
Python and cannot be pip-installed into a venv. Raven's capture service explicitly
uses `/usr/bin/python3` for engine subprocesses while the FastAPI backend runs in
the venv.

**Flowgraphs:** Pre-built `.grc` files in `flowgraphs/` can be compiled to Python
with `grcc` and run standalone.

---

## FISSURE

**Used by:** FissureService (`backend/services/fissure_service.py`)

Raven reads FISSURE's Flow Graph Library CSV to look up protocols by frequency
and modulation, and can launch FISSURE's modulation detection flowgraphs.

**Prerequisites:**
- FISSURE installed (default: `/home/kama/Tools/FISSURE`)
- Flow Graph Library CSV present

**Configuration:**
```yaml
fissure:
  install_path: "/home/kama/Tools/FISSURE"
  enabled: true
```

**What Raven uses from FISSURE:**
- Protocol database (CSV) — frequency, modulation, bandwidth mappings
- Demodulation flowgraphs — GRC files for known protocol demod
- Attack flowgraphs — GRC files for TX-capable operations (ROE required)
- Modulation detection — TSI classification flowgraph subprocess

**What Raven does NOT do:** Raven does not replace FISSURE's GUI. The
`POST /api/fissure/launch` endpoint opens the full FISSURE dashboard for
manual protocol analysis.

---

## gpsd

**Used by:** GPSPoller (`backend/services/gps_poller.py`)

Raven connects to gpsd over TCP (default `127.0.0.1:2947`) and polls for position
fixes. GPS data is attached to signal events for geolocation and displayed on the
tactical map.

**Prerequisites:**
- GPS receiver connected (USB u-blox recommended)
- gpsd running: `sudo systemctl enable --now gpsd`
- Device configured in `/etc/default/gpsd`:
  ```
  DEVICES="/dev/ttyACM0"
  GPSD_OPTIONS="-n"
  ```

**Verify:** `cgps` or `gpsmon` should show a fix before starting Raven.

**Configuration:**
```yaml
gps:
  enabled: true
  host: "127.0.0.1"
  port: 2947
  poll_interval: 2
```

---

## Tools NOT Directly Integrated

### URH (Universal Radio Hacker)

Raven does not call URH directly. Use URH for:
- Manual protocol analysis of captured IQ files
- Bit-level decoding of unknown signals
- Generating classifier rules from decoded protocols

**Workflow:** Capture IQ with Raven's squelch recorder → open `.cf32` in URH →
decode → add matching rule to `backend/classifier/rules/`.

### GQRX / SDR++

Not integrated. Use as manual waterfall verification tools alongside Raven's
automated waterfall. Useful for confirming what Raven's alerter flags.

### SDRangel / CubicSDR

Not integrated. Alternative spectrum analysis tools available on DragonOS.

---

## EMCON Mode

Raven does not yet have a single EMCON toggle, but you can achieve emissions
control by:

1. **Disable GPS polling:** Set `gps.enabled: false` in config
2. **Disable federation beacons:** Set `federation.enabled: false` (default)
3. **TX is off by default** — no action needed
4. **Reduce network exposure:** Bind to `127.0.0.1` instead of `0.0.0.0`
5. **WiFi/BT off:** Use the DragonOS `emcon-on.sh` script before deploying

Future: A `POST /api/emcon/enable` endpoint that toggles all of the above atomically.
