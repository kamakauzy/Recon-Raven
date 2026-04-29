# Templates

Field-printable markdown templates for SIGINT operations.

## Files

### `signal-log.md`

Blank signal log for manual field use. One row per observed signal. Includes:
- Session metadata (date, location, operator, equipment)
- 10-row signal log table (frequency, modulation, bearing, classification, threat level)
- Classification key (V=Voice, D=Data, E=Encrypted, B=Beacon, W=Wideband, U=Unknown)
- Threat level scale (0=known friendly → 4=confirmed hostile)

**Usage:** Copy the file, fill during collection. Maps directly to the
[field checklist](../reference/field-checklist.md) Step 3 (Investigate → Log).

### Automated Reports

The `engine/intel_packager.py` script generates markdown intel summaries
automatically. The scheduler runs it daily at midnight (configurable via
`scheduler.report_cron`). Reports are stored in the configured `report_dir`
(default: `/var/lib/recon-raven/reports/`).

**Input sources** (auto-discovered from `log_dir`):
| File Pattern | Source | Data |
|-------------|--------|------|
| `*burst*` | burst_detector.py | Frequency, duration, peak power, IQ file path |
| `*alert*` | signal_alerter.py | Frequency, power level, alert number |
| `*bearing*` / `*df*` | Manual or DF solver | Bearing, frequency, confidence |
| `*diff*` | baseline_diff.py | New signals, disappeared, power changes |

**Output format:** Markdown with sections:
1. Executive Summary — time window, total events, top frequencies
2. Signal Activity — burst and alert tables sorted by frequency
3. DF Bearings — bearing measurements (if available)
4. Baseline Changes — new/disappeared/changed signals
5. Recommendations — auto-generated based on anomaly count

**Manual generation:**
```bash
# From specific files
./engine/intel_packager.py --bursts logs/bursts.csv --alerts logs/alerts.csv -o report.md

# Auto-discover all logs in a directory
./engine/intel_packager.py --all /var/lib/recon-raven/logs/ -o report.md

# With baseline diff
./engine/intel_packager.py --bursts bursts.csv --baseline-diff diff.txt -o report.md
```

**API trigger:**
```bash
# Trigger report generation via API
curl -X POST http://localhost:8080/api/scheduler/trigger/auto_report
```
