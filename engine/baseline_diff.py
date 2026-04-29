#!/usr/bin/env python3
"""
Baseline diff — compares two rtl_433 CSV baselines and reports changes.

Detects: new signals, disappeared signals, significant power changes,
changed repetition rates. Core ANALYZE phase tool for F3EAD.

Reads rtl_433 CSV output (standard columns: time, model, id, channel, etc.)

Usage:
    ./baseline_diff.py baseline_old.csv baseline_new.csv
    ./baseline_diff.py baseline_old.csv baseline_new.csv --threshold 10
    ./baseline_diff.py baseline_old.csv baseline_new.csv -o diff_report.txt
"""

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def parse_rtl433_csv(filepath):
    """Parse rtl_433 CSV into a list of signal observations."""
    signals = []
    path = Path(filepath)
    if not path.exists():
        print(f"[ERROR] File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    with open(path, "r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # rtl_433 CSV has varying columns; normalize what we need
            sig_entry = {
                "time": row.get("time", row.get("Time", "")),
                "model": row.get("model", row.get("Model", "unknown")),
                "id": row.get("id", row.get("ID", row.get("device", ""))),
                "channel": row.get("channel", row.get("Channel", "")),
                "freq": row.get("freq", row.get("Freq", row.get("frequency", ""))),
                "rssi": _safe_float(
                    row.get("rssi", row.get("RSSI", row.get("snr", "")))
                ),
            }
            signals.append(sig_entry)
    return signals


def _safe_float(val):
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def build_fingerprint(sig_entry):
    """Create a unique-ish identifier for a signal source."""
    parts = [
        sig_entry.get("model", ""),
        str(sig_entry.get("id", "")),
        str(sig_entry.get("channel", "")),
    ]
    return "|".join(p for p in parts if p)


def analyze_baseline(signals):
    """Group signals by fingerprint, compute stats."""
    groups = defaultdict(
        lambda: {"count": 0, "rssi_values": [], "times": [], "freqs": set()}
    )
    for s in signals:
        fp = build_fingerprint(s)
        if not fp or fp == "||":
            fp = f"unknown_{s.get('freq', 'nofreq')}"
        g = groups[fp]
        g["count"] += 1
        if s["rssi"] is not None:
            g["rssi_values"].append(s["rssi"])
        g["times"].append(s["time"])
        if s.get("freq"):
            g["freqs"].add(s["freq"])
    # Compute averages
    for fp, g in groups.items():
        rssi_vals = g["rssi_values"]
        g["avg_rssi"] = sum(rssi_vals) / len(rssi_vals) if rssi_vals else None
        g["peak_rssi"] = max(rssi_vals) if rssi_vals else None
        g["freq_str"] = ", ".join(sorted(g["freqs"])) if g["freqs"] else "unknown"
    return groups


def diff_baselines(old_groups, new_groups, threshold_db):
    """Compare two baselines and generate a diff report."""
    report = {
        "new_signals": [],
        "disappeared": [],
        "power_changes": [],
        "rate_changes": [],
    }

    all_fps = set(list(old_groups.keys()) + list(new_groups.keys()))

    for fp in sorted(all_fps):
        old = old_groups.get(fp)
        new = new_groups.get(fp)

        if old is None and new is not None:
            report["new_signals"].append(
                {
                    "fingerprint": fp,
                    "count": new["count"],
                    "avg_rssi": new["avg_rssi"],
                    "freq": new["freq_str"],
                }
            )
        elif new is None and old is not None:
            report["disappeared"].append(
                {
                    "fingerprint": fp,
                    "count": old["count"],
                    "avg_rssi": old["avg_rssi"],
                    "freq": old["freq_str"],
                }
            )
        else:
            # Both exist — check for changes
            if old["avg_rssi"] is not None and new["avg_rssi"] is not None:
                delta = new["avg_rssi"] - old["avg_rssi"]
                if abs(delta) >= threshold_db:
                    report["power_changes"].append(
                        {
                            "fingerprint": fp,
                            "old_rssi": old["avg_rssi"],
                            "new_rssi": new["avg_rssi"],
                            "delta": delta,
                            "freq": new["freq_str"],
                        }
                    )

            # Rate change (significant count difference, normalized)
            if old["count"] > 5 and new["count"] > 5:
                ratio = new["count"] / old["count"]
                if ratio > 2.0 or ratio < 0.5:
                    report["rate_changes"].append(
                        {
                            "fingerprint": fp,
                            "old_count": old["count"],
                            "new_count": new["count"],
                            "ratio": ratio,
                            "freq": new["freq_str"],
                        }
                    )

    return report


def format_report(report, old_file, new_file):
    """Format the diff report as readable text."""
    lines = []
    lines.append("=" * 60)
    lines.append("  BASELINE DIFF REPORT")
    lines.append("=" * 60)
    lines.append(f"  Old: {old_file}")
    lines.append(f"  New: {new_file}")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)
    lines.append("")

    # ── New signals (CRITICAL — potential threats)
    lines.append(f"{'─' * 60}")
    lines.append(f"  NEW SIGNALS ({len(report['new_signals'])})")
    lines.append(f"{'─' * 60}")
    if report["new_signals"]:
        for s in report["new_signals"]:
            rssi_str = f"{s['avg_rssi']:.1f} dB" if s["avg_rssi"] is not None else "N/A"
            lines.append(f"  [!] {s['fingerprint']}")
            lines.append(
                f"      Freq: {s['freq']}  |  Count: {s['count']}  |  Avg RSSI: {rssi_str}"
            )
    else:
        lines.append("  (none)")
    lines.append("")

    # ── Disappeared signals
    lines.append(f"{'─' * 60}")
    lines.append(f"  DISAPPEARED SIGNALS ({len(report['disappeared'])})")
    lines.append(f"{'─' * 60}")
    if report["disappeared"]:
        for s in report["disappeared"]:
            rssi_str = f"{s['avg_rssi']:.1f} dB" if s["avg_rssi"] is not None else "N/A"
            lines.append(f"  [-] {s['fingerprint']}")
            lines.append(
                f"      Freq: {s['freq']}  |  Was count: {s['count']}  |  Was RSSI: {rssi_str}"
            )
    else:
        lines.append("  (none)")
    lines.append("")

    # ── Power changes
    lines.append(f"{'─' * 60}")
    lines.append(f"  POWER CHANGES ({len(report['power_changes'])})")
    lines.append(f"{'─' * 60}")
    if report["power_changes"]:
        for s in sorted(
            report["power_changes"], key=lambda x: abs(x["delta"]), reverse=True
        ):
            direction = "▲" if s["delta"] > 0 else "▼"
            lines.append(f"  [{direction}] {s['fingerprint']}")
            lines.append(
                f"      Freq: {s['freq']}  |  {s['old_rssi']:.1f} → {s['new_rssi']:.1f} dB  ({s['delta']:+.1f} dB)"
            )
    else:
        lines.append("  (none)")
    lines.append("")

    # ── Rate changes
    lines.append(f"{'─' * 60}")
    lines.append(f"  REPETITION RATE CHANGES ({len(report['rate_changes'])})")
    lines.append(f"{'─' * 60}")
    if report["rate_changes"]:
        for s in report["rate_changes"]:
            direction = "▲" if s["ratio"] > 1 else "▼"
            lines.append(f"  [{direction}] {s['fingerprint']}")
            lines.append(
                f"      Freq: {s['freq']}  |  {s['old_count']} → {s['new_count']} observations ({s['ratio']:.1f}x)"
            )
    else:
        lines.append("  (none)")
    lines.append("")

    # ── Summary
    total_anomalies = (
        len(report["new_signals"])
        + len(report["disappeared"])
        + len(report["power_changes"])
        + len(report["rate_changes"])
    )
    lines.append("=" * 60)
    lines.append(f"  TOTAL ANOMALIES: {total_anomalies}")
    if report["new_signals"]:
        lines.append(
            f"  *** {len(report['new_signals'])} NEW SIGNAL(S) DETECTED — INVESTIGATE ***"
        )
    lines.append("=" * 60)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Compare two rtl_433 CSV baselines — detect RF environment changes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s baselines/day1.csv baselines/day2.csv
  %(prog)s old.csv new.csv --threshold 5 -o ~/SIGINT/logs/diff.txt
  %(prog)s yesterday.csv today.csv | head -40

Anomaly types:
  NEW SIGNALS       — Not in old baseline. Potential threat. Investigate immediately.
  DISAPPEARED       — Was in old baseline, now gone. Source moved or powered off.
  POWER CHANGES     — Same source, significant strength change. Source moved closer/further.
  RATE CHANGES      — Same source, transmitting more/less often. Behavior change.
        """,
    )
    parser.add_argument("old_baseline", help="Path to the older/reference baseline CSV")
    parser.add_argument(
        "new_baseline", help="Path to the newer baseline CSV to compare"
    )
    parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=6.0,
        help="Power change threshold in dB to report (default: 6)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Write report to file (default: stdout)",
    )

    args = parser.parse_args()

    # Parse
    old_signals = parse_rtl433_csv(args.old_baseline)
    new_signals = parse_rtl433_csv(args.new_baseline)

    if not old_signals:
        print(
            f"[WARN] Old baseline has 0 entries: {args.old_baseline}", file=sys.stderr
        )
    if not new_signals:
        print(
            f"[WARN] New baseline has 0 entries: {args.new_baseline}", file=sys.stderr
        )

    # Analyze
    old_groups = analyze_baseline(old_signals)
    new_groups = analyze_baseline(new_signals)

    # Diff
    report = diff_baselines(old_groups, new_groups, args.threshold)

    # Format
    output = format_report(report, args.old_baseline, args.new_baseline)

    # Output
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
        print(f"[OK] Report written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
