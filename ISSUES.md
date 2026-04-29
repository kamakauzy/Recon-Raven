# Recon-Raven Issue Tracker

Feedback evaluation from external review (April 2026). Assessed against current state post-Phase 9 deployment.

---

## Triage Summary

| # | Issue | Severity | Status | Verdict |
|---|-------|----------|--------|---------|
| 1 | README is empty/useless | CRITICAL | **RESOLVED** | Rewritten with arch diagram, API ref, install guide, structure, TX safety |
| 2 | Repo is scaffolding / no working code | CRITICAL | **RESOLVED** | All 9 phases coded, deployed, verified on Dragon box (potato:8080) |
| 3 | Scope creep risk | HIGH | OPEN | Code exists but needs field validation per-phase |
| 4 | No integration docs (rtl_433, URH, GQRX, EMCON) | HIGH | **RESOLVED** | docs/INTEGRATION.md covers all tools + EMCON |
| 5 | No screenshots / visual proof | MEDIUM | OPEN | Dashboard serves but no captured screenshots |
| 6 | No one-command install script | MEDIUM | **RESOLVED** | install.sh with venv, deps, config, systemd |
| 7 | TX safety disclaimers insufficient | HIGH | **RESOLVED** | LEGAL.md + README warning banner + TX enable confirmation |
| 8 | No F3EAD "how this supports the course" section | MEDIUM | **RESOLVED** | F3EAD Integration table + Course Day Mapping in README |
| 9 | No MVP prioritization / phased delivery proof | LOW | **RESOLVED** | Baseline→alert→dashboard→classifier is the actual build order |
| 10 | Intel package export not linked to templates/ | MEDIUM | **RESOLVED** | templates/README.md with format docs + usage examples |

---

## OPEN Issues — Action Plan

### Issue 3: Scope Validation

**Problem:** 9 phases built rapidly. Each needs field testing against real RF to confirm it's not vaporware.

**Plan:**
- [ ] Run a full baseline capture cycle (rtl_433 → CSV → diff → report)
- [ ] Verify burst_detector fires events through WebSocket → Push chain
- [ ] DF solver: take 2+ real bearings with RTL-SDR and KerberosSDR or manual rotation
- [ ] TX: connect HackRF, enable TX, transmit test tone on 70cm, verify audit log
- [ ] FISSURE: populate protocol CSV, verify query returns valid flowgraph paths
- [ ] Federation: spin up 2nd Raven node (VM or laptop), confirm multicast discovery
- [ ] Classifier: capture known signal (weather sensor), confirm correct rule match

**Priority:** HIGH — nothing ships to students until at least baseline + alert + classify path is validated end-to-end.

---

### Issue 4: Integration Documentation

**Problem:** The tool wraps rtl_433, rtl_power, GNU Radio, FISSURE, gpsd — but doesn't explain the relationship or prerequisites clearly.

**Plan:**
- [ ] Create `docs/INTEGRATION.md` covering:
  - rtl_433: how baselines use it, expected output format, custom conf support
  - rtl_power: how signal_alerter invokes it, threshold tuning
  - GNU Radio: osmosdr source blocks in burst_detector/squelch_recorder, version requirements
  - FISSURE: where to place Flow Graph Library CSV, how protocol queries work
  - gpsd: required setup, u-blox configuration, NMEA vs binary
  - URH: not integrated yet — document as "use for manual protocol analysis, export to classifier rules"
  - GQRX: not integrated — document as "manual waterfall verification tool"
- [ ] Add EMCON mode documentation (kill all TX, reduce poll intervals, disable beacons)

**Priority:** HIGH — students won't adopt what they can't install.

---

### Issue 5: Screenshots

**Problem:** No visual evidence the dashboard works. GitHub repos without screenshots get ignored.

**Plan:**
- [ ] Capture waterfall canvas with active signal
- [ ] Capture Leaflet map with GPS fix + event markers
- [ ] Capture terminal showing startup logs (all services loaded)
- [ ] Add `docs/screenshots/` directory
- [ ] Embed in README hero section

**Priority:** MEDIUM — cosmetic but critical for adoption.

---

### Issue 6: One-Command Install

**Problem:** Install requires 6+ steps. DragonOS students need `curl | bash` simplicity.

**Plan:**
- [ ] Create `install.sh`:
  ```
  #!/bin/bash
  # Recon-Raven installer for DragonOS / Ubuntu 22.04+
  # Checks: python3, gpsd, rtl_433, GNU Radio
  # Creates: venv, config.yml from example, data dirs, systemd unit
  ```
- [ ] Detect DragonOS vs vanilla Ubuntu and adjust paths
- [ ] Optionally install systemd service
- [ ] Test on fresh DragonOS ISO

**Priority:** MEDIUM — reduces friction from "clone and figure it out" to "run one thing."

---

### Issue 7: TX Legal Disclaimer

**Problem:** README explains the safety model but lacks a scary-enough legal banner. Civilians WILL get arrested transmitting on unauthorized frequencies.

**Plan:**
- [ ] Add prominent WARNING block at top of README (before architecture):
  ```
  ⚠️ LEGAL WARNING: RF transmission features are for AUTHORIZED TRAINING ONLY.
  Unauthorized transmission violates FCC Part 97/15 (US), Wireless Telegraphy Act (UK),
  and equivalent laws globally. TX is DISABLED by default and requires explicit
  ROE approval. Misuse = federal felony. You have been warned.
  ```
- [ ] Add LEGAL.md with full disclaimer, safe harbor language
- [ ] TX enable endpoint should log a confirmation prompt (already does audit — add CLI confirmation on first enable)
- [ ] Startup log should print "TX: DISABLED — see ROE" prominently

**Priority:** HIGH — liability shield. Non-negotiable for course distribution.

---

### Issue 8: F3EAD Course Integration Section

**Problem:** Reference docs (f3ead-cycle.md, field-checklist.md, signal-types.md) exist but the README doesn't explain how Raven automates each F3EAD phase.

**Plan:**
- [ ] Add "F3EAD Integration" section to README mapping phases to features:
  | F3EAD Phase | Raven Feature | Reference Doc |
  |-------------|---------------|---------------|
  | Find | Baseline + anomaly alerter | field-checklist.md |
  | Fix | DF solver triangulation | direction-finding.md |
  | Finish | TX deception inject (OPFOR only) | — |
  | Exploit | FISSURE protocol decode | signal-types.md |
  | Analyze | Classifier + intel packager | f3ead-cycle.md |
  | Disseminate | Report export + federation share | — |
- [ ] Link each reference doc from the table
- [ ] Add "Course Day Mapping" showing which features support Day 1-5 curriculum

**Priority:** MEDIUM — differentiator. This is what makes it a course tool vs. yet another SDR project.

---

### Issue 10: Intel Package / Template Docs

**Problem:** `templates/` dir and `engine/intel_packager.py` exist. Scheduler runs daily report. But there's no documentation on output format or how to customize.

**Plan:**
- [ ] Document template format in `templates/README.md`
- [ ] Add example output (redacted) to `docs/examples/`
- [ ] Link from main README under "Reports" section

**Priority:** LOW — functional but undocumented.

---

## Resolved Issues (No Action Needed)

### Issue 1: README — FIXED
Rewritten commit `b1717f9`. Now contains architecture, features, install, API ref, structure, TX safety, federation.

### Issue 2: No Working Code — FIXED
23 files, 2282 LOC across Phases 2-8 (commit `9fdaf8b`), Phase 9 (commit `b229dc3`). Deployed and API-tested on Dragon box.

### Issue 9: No MVP Prioritization — FIXED
Build order was exactly: baseline logger → capture engine → dashboard → classifier → DF → TX → FISSURE → push → federation. Matches recommended MVP path.

---

## Proposed Execution Order

1. **Issue 7** — TX disclaimer (30 min, non-negotiable for any public sharing)
2. **Issue 3** — Field validation on Dragon box (2-4 hours, proves it's not vaporware)
3. **Issue 4** — Integration docs (1-2 hours)
4. **Issue 8** — F3EAD course section in README (30 min)
5. **Issue 5** — Screenshots during field validation (free if done with #3)
6. **Issue 6** — Install script (1 hour)
7. **Issue 10** — Template docs (30 min)
