# Field Execution Checklist

Use this every time you deploy for signal collection.

---

## 1. ESTABLISH BASELINE
- [ ] Boot into DragonOS
- [ ] Run 30-minute `rtl_433` baseline on known bands
- [ ] Export CSV and note start time
- [ ] Compare against previous baseline — flag changes

## 2. SWEEP
- [ ] Quick 2-minute sweep with TinySA or wideband SDR
- [ ] Note any new spikes, bursts, or activity
- [ ] Check all four tactical bands (VHF, UHF, 433 MHz, 915 MHz)

## 3. INVESTIGATE
- [ ] On anomalies: switch to laptop with GQRX or SDR++
- [ ] Record 30–60 seconds in URH or GQRX
- [ ] Take minimum 2 DF bearings from different positions
- [ ] Log in signal log template

## 4. DECIDE & REPORT
- [ ] Apply F3EAD cycle (see `f3ead-cycle.md`)
- [ ] Classify signal using signal types reference
- [ ] Make team decision: monitor / reposition / evade / act
- [ ] Package findings into intelligence report

---

## EMCON Reminders
- [ ] WiFi and Bluetooth OFF before deploying (`emcon-on.sh`)
- [ ] Minimize screen brightness and RF emissions
- [ ] USB extension cable on SDR dongle (isolate laptop noise)
- [ ] Antenna orientation matches expected signal polarization

## Intelligence Package (Minimum Fields)
| Field | Value |
|-------|-------|
| Frequency | |
| Modulation | |
| Bearing(s) | |
| Time observed | |
| Signal behavior | |
| Threat level (0–4) | |
| Confidence (low/med/high) | |
| Recommended action | |
