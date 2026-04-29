# Recon-Raven

**F3EAD-aligned SIGINT automation platform** — multi-SDR orchestration, real-time spectrum dashboard, signal classification, direction finding, HackRF TX with safety gates, FISSURE integration, and peer-to-peer federation.

Built for DragonOS on field-deployable Linux boxes with RTL-SDR and HackRF hardware.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (PWA)         http://<host>:8080                   │
│  ├── Waterfall canvas   (WebSocket /ws/spectrum)             │
│  ├── Leaflet map        (GPS + event markers)                │
│  └── Push notifications (Web Push API)                       │
├─────────────────────────────────────────────────────────────┤
│  FastAPI Backend                                             │
│  ├── DeviceManager      (RTL-SDR / HackRF enumeration)      │
│  ├── CaptureService     (GNU Radio engine subprocess mgmt)   │
│  ├── Classifier         (YAML rules + ML pipeline)           │
│  ├── Scheduler          (APScheduler cron: baselines/diffs)  │
│  ├── DFSolver           (Weighted least-squares triangulation│
│  ├── TXService          (5 safety gates, audit log)          │
│  ├── FissureService     (Protocol DB, modulation detection)  │
│  ├── PushService        (pywebpush mobile alerts)            │
│  └── FederationService  (UDP multicast mesh discovery)       │
├─────────────────────────────────────────────────────────────┤
│  Engine Scripts (GNU Radio / rtl_power / rtl_433)            │
│  ├── burst_detector.py      squelch_recorder.py             │
│  ├── signal_alerter.py      power_logger.py                 │
│  ├── baseline_diff.py       intel_packager.py               │
└─────────────────────────────────────────────────────────────┘
```

## Features

| Capability | Description |
|------------|-------------|
| **Multi-SDR capture** | Concurrent GNU Radio subprocesses across multiple RTL-SDR/HackRF devices |
| **Real-time waterfall** | Canvas 2D spectrum display with viridis colormap via WebSocket |
| **GPS tracking** | gpsd integration with Leaflet map, event geolocation |
| **Signal classification** | Rule-based (YAML) + ML pipeline — weather sensors, LoRa, TPMS, OOK, digital voice |
| **Scheduled baselines** | Cron-driven rtl_433 captures with automatic diff reports |
| **Direction finding** | Weighted least-squares bearing intersection with CEP estimation |
| **HackRF TX** | 5 safety gates: freq whitelist, power cap (30 dB), duration limit, RF amp block, full audit log |
| **FISSURE** | Protocol database query, modulation detection, demod/attack flowgraph lookup |
| **Push alerts** | Web Push notifications on signal events (bursts, anomalies) |
| **Federation** | UDP multicast peer discovery, automatic event sharing between Raven nodes |
| **PWA** | Installable on mobile, offline service worker |

## Quick Start

### Requirements

- **OS:** DragonOS / Ubuntu 22.04+ with GNU Radio 3.10+
- **Hardware:** 1+ RTL-SDR Blog V4, optional HackRF One, USB GPS (u-blox)
- **Software:** Python 3.11+, gpsd, rtl_433, rtl_power

### Install

```bash
git clone https://github.com/kamakauzy/Recon-Raven.git
cd Recon-Raven

# Create venv (required on Ubuntu 24.04+ due to PEP 668)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp config.example.yml config.yml
# Edit config.yml — set data_dir, GPS, TX bands, FISSURE path

# Create data directories
sudo mkdir -p /var/lib/recon-raven/{captures,logs,baselines,reports}
sudo chown $USER:$USER /var/lib/recon-raven
```

### Run

```bash
source venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8080
```

Open `http://<your-ip>:8080` in a browser.

### Systemd (production)

```ini
# /etc/systemd/system/recon-raven.service
[Unit]
Description=Recon-Raven SIGINT Platform
After=network.target gpsd.service

[Service]
Type=simple
User=kama
WorkingDirectory=/home/kama/Recon-Raven
ExecStart=/home/kama/Recon-Raven/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now recon-raven
```

## API Reference

All endpoints are prefixed with `/api/`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | System health, uptime, device/GPS status |
| GET | `/devices` | List SDR devices |
| GET | `/gps` | Current GPS fix |
| POST | `/captures/start` | Start a capture engine |
| POST | `/captures/stop/{id}` | Stop a running capture |
| GET | `/events` | Query signal events |
| GET | `/baselines` | List baseline captures |
| GET | `/scheduler/jobs` | List scheduled jobs |
| POST | `/scheduler/trigger/{id}` | Manually trigger a job |
| GET | `/classifier/rules` | List classification rules |
| POST | `/classifier/classify` | Classify a signal |
| POST | `/df/solve` | Triangulate TX from bearings |
| GET | `/tx/status` | TX service status + safety config |
| POST | `/tx/transmit` | Transmit (requires TX enabled) |
| GET | `/fissure/status` | FISSURE availability |
| GET | `/fissure/protocols` | Search protocol database |
| POST | `/push/subscribe` | Register push subscription |
| GET | `/federation/status` | Federation mesh status |
| GET | `/federation/peers` | List discovered peers |

### WebSocket Endpoints

| Path | Description |
|------|-------------|
| `/ws/spectrum` | Real-time power spectral density frames |
| `/ws/alerts` | Signal event stream (bursts, anomalies) |
| `/ws/status` | System status updates |

## Project Structure

```
Recon-Raven/
├── backend/
│   ├── api/
│   │   ├── routes.py          # REST API endpoints
│   │   └── websocket.py       # WebSocket handlers
│   ├── classifier/
│   │   ├── features.py        # IQ feature extraction
│   │   └── rules/             # YAML classification rules
│   ├── db/
│   │   ├── database.py        # SQLAlchemy async engine
│   │   └── models.py          # ORM models
│   ├── services/
│   │   ├── capture_service.py
│   │   ├── classifier.py
│   │   ├── device_manager.py
│   │   ├── df_solver.py
│   │   ├── federation_service.py
│   │   ├── fissure_service.py
│   │   ├── gps_poller.py
│   │   ├── push_service.py
│   │   ├── scheduler.py
│   │   └── tx_service.py
│   ├── config.py
│   └── main.py               # FastAPI app + lifespan
├── engine/
│   ├── burst_detector.py      # GNU Radio burst detection
│   ├── squelch_recorder.py    # Squelch-triggered IQ recorder
│   ├── signal_alerter.py      # rtl_power threshold alerter
│   ├── power_logger.py        # Wideband power sweep logger
│   ├── baseline_diff.py       # Baseline comparison
│   └── intel_packager.py      # Daily report generator
├── frontend/
│   ├── index.html
│   ├── js/
│   │   ├── spectrum.js        # Waterfall renderer
│   │   └── map.js             # Leaflet GPS/event map
│   ├── css/
│   ├── manifest.json          # PWA manifest
│   └── sw.js                  # Service worker
├── flowgraphs/                # GNU Radio .grc files
├── config.example.yml
├── requirements.txt
└── README.md
```

## TX Safety Model

HackRF transmission is gated by **5 independent safety checks** — all must pass:

1. **TX master enable** — disabled by default, requires explicit `POST /api/tx/enable`
2. **Frequency whitelist** — only amateur bands (144–148, 420–450, 902–928 MHz)
3. **Power cap** — gain hard-capped at 30 dB (hardware max is 47)
4. **Duration limit** — auto-kill after 30 seconds
5. **RF amplifier block** — external PA enable line is always forced off

Every TX attempt (approved or rejected) is written to an immutable audit log.

## Federation

When multiple Raven nodes are on the same LAN, they discover each other via UDP multicast (`239.42.42.42:8042`) and automatically share signal events. Enable in `config.yml`:

```yaml
federation:
  enabled: true
```

Each node appears as a peer with GPS position, device count, and queryable event history.

## License

See [LICENSE](LICENSE).
