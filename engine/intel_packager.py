#!/usr/bin/env python3
"""
Intel packager — generates a one-page SIGINT intelligence summary.

Ingests signal logs (burst CSV, alert CSV, rtl_433 baseline) and optional
DF bearing data, then produces a formatted markdown intel report ready for
dissemination. F3EAD DISSEMINATE phase.

Designed to be the final step in the collection-to-reporting pipeline:
  burst_detector → baseline_diff → intel_packager → one-page summary

Usage:
    ./intel_packager.py --bursts ~/SIGINT/logs/bursts.csv
    ./intel_packager.py --bursts bursts.csv --alerts alerts.csv --bearings df.csv
    ./intel_packager.py --bursts bursts.csv --baseline-diff diff.txt -o report.md
    ./intel_packager.py --all ~/SIGINT/logs/   # auto-discover all log files
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def parse_bursts_csv(filepath):
    """Parse burst_detector.py output CSV."""
    bursts = []
    if not filepath or not Path(filepath).exists():
        return bursts
    with open(filepath, "r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bursts.append(
                {
                    "time": row.get("timestamp_utc", ""),
                    "freq": row.get("freq_mhz", ""),
                    "duration_ms": _safe_float(row.get("duration_ms", "")),
                    "peak_db": _safe_float(row.get("peak_power_db", "")),
                    "iq_file": row.get("iq_file", ""),
                }
            )
    return bursts


def parse_alerts_csv(filepath):
    """Parse signal_alerter.py output CSV."""
    alerts = []
    if not filepath or not Path(filepath).exists():
        return alerts
    with open(filepath, "r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            alerts.append(
                {
                    "time": row.get("timestamp_utc", ""),
                    "freq": row.get("freq_mhz", ""),
                    "power_db": _safe_float(row.get("power_db", "")),
                    "alert_num": row.get("alert_num", ""),
                }
            )
    return alerts


def parse_bearings_csv(filepath):
    """Parse DF bearing data (simple CSV: timestamp, freq, bearing_deg, confidence)."""
    bearings = []
    if not filepath or not Path(filepath).exists():
        return bearings
    with open(filepath, "r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bearings.append(
                {
                    "time": row.get("timestamp", row.get("timestamp_utc", "")),
                    "freq": row.get("freq", row.get("freq_mhz", "")),
                    "bearing": _safe_float(
                        row.get("bearing", row.get("bearing_deg", ""))
                    ),
                    "confidence": row.get("confidence", ""),
                }
            )
    return bearings


def read_baseline_diff(filepath):
    """Read a baseline_diff.py text report."""
    if not filepath or not Path(filepath).exists():
        return None
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _safe_float(val):
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def auto_discover_logs(log_dir):
    """Find all relevant log files in a directory."""
    p = Path(log_dir)
    found = {}
    for f in p.iterdir():
        if not f.is_file():
            continue
        name = f.name.lower()
        if "burst" in name and name.endswith(".csv"):
            found.setdefault("bursts", f)
        elif "alert" in name and name.endswith(".csv"):
            found.setdefault("alerts", f)
        elif "bearing" in name and name.endswith(".csv"):
            found.setdefault("bearings", f)
        elif "diff" in name and name.endswith(".txt"):
            found.setdefault("baseline_diff", f)
    return found


def generate_report(bursts, alerts, bearings, baseline_diff_text, args):
    """Generate the intel summary markdown."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = []

    # ── Header
    lines.append("# SIGINT Intelligence Summary")
    lines.append("")
    lines.append(f"**Generated:** {now}  ")
    lines.append("**Classification:** UNCLASSIFIED // FOUO  ")
    if args.title:
        lines.append(f"**Operation:** {args.title}  ")
    if args.location:
        lines.append(f"**Location:** {args.location}  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Executive Summary
    lines.append("## Executive Summary")
    lines.append("")
    total_bursts = len(bursts)
    total_alerts = len(alerts)
    total_bearings = len(bearings)

    if total_bursts == 0 and total_alerts == 0:
        lines.append("No significant RF activity detected during collection period.")
    else:
        # Frequency breakdown
        freq_counter = Counter()
        for b in bursts:
            if b["freq"]:
                freq_counter[b["freq"]] += 1
        for a in alerts:
            if a["freq"]:
                freq_counter[a["freq"]] += 1

        lines.append(
            f"- **{total_bursts}** burst(s) detected across **{len(freq_counter)}** frequency/frequencies"
        )
        lines.append(f"- **{total_alerts}** threshold alert(s) triggered")
        if total_bearings:
            lines.append(f"- **{total_bearings}** DF bearing(s) recorded")

        # Time span
        all_times = [b["time"] for b in bursts if b["time"]] + [
            a["time"] for a in alerts if a["time"]
        ]
        if all_times:
            all_times_sorted = sorted(all_times)
            lines.append(
                f"- Collection window: `{all_times_sorted[0]}` → `{all_times_sorted[-1]}`"
            )

        # Top frequencies
        if freq_counter:
            lines.append("")
            lines.append("**Most active frequencies:**")
            for freq, count in freq_counter.most_common(5):
                lines.append(f"  - {freq} MHz — {count} event(s)")

    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Burst Analysis
    if bursts:
        lines.append("## Burst Activity")
        lines.append("")
        lines.append(f"Total bursts: **{total_bursts}**")
        lines.append("")

        # Group by frequency
        by_freq = defaultdict(list)
        for b in bursts:
            by_freq[b.get("freq", "unknown")].append(b)

        for freq in sorted(by_freq.keys()):
            fb = by_freq[freq]
            durations = [b["duration_ms"] for b in fb if b["duration_ms"] is not None]
            powers = [b["peak_db"] for b in fb if b["peak_db"] is not None]

            lines.append(f"### {freq} MHz ({len(fb)} bursts)")
            lines.append("")
            if durations:
                lines.append("| Metric | Value |")
                lines.append("|--------|-------|")
                lines.append(f"| Min duration | {min(durations):.1f} ms |")
                lines.append(f"| Max duration | {max(durations):.1f} ms |")
                lines.append(
                    f"| Avg duration | {sum(durations) / len(durations):.1f} ms |"
                )
                if powers:
                    lines.append(f"| Peak power | {max(powers):.1f} dB |")
                    lines.append(f"| Avg power | {sum(powers) / len(powers):.1f} dB |")
                lines.append("")

            # Pattern of life — activity by hour
            hours = Counter()
            for b in fb:
                t = b.get("time", "")
                if len(t) >= 13:
                    try:
                        h = t[11:13]
                        hours[h] += 1
                    except (IndexError, ValueError):
                        pass

            if hours:
                lines.append("**Activity by hour (UTC):**")
                lines.append("```")
                for h in sorted(hours.keys()):
                    bar = "█" * min(hours[h], 40)
                    lines.append(f"  {h}:00  {bar} ({hours[h]})")
                lines.append("```")
                lines.append("")

        lines.append("---")
        lines.append("")

    # ── Alerts
    if alerts:
        lines.append("## Threshold Alerts")
        lines.append("")
        lines.append(f"Total alerts: **{total_alerts}**")
        lines.append("")
        lines.append("| # | Time (UTC) | Freq (MHz) | Power (dB) |")
        lines.append("|---|-----------|-----------|-----------|")
        for a in alerts[-20:]:  # Last 20 alerts
            lines.append(
                f"| {a.get('alert_num', '?')} | {a['time']} | {a['freq']} | {a.get('power_db', 'N/A')} |"
            )
        if len(alerts) > 20:
            lines.append(f"| ... | *{len(alerts) - 20} more alerts omitted* | | |")
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── DF Bearings
    if bearings:
        lines.append("## Direction-Finding Bearings")
        lines.append("")
        lines.append(f"Total bearings: **{total_bearings}**")
        lines.append("")
        lines.append("| Time | Freq (MHz) | Bearing (°) | Confidence |")
        lines.append("|------|-----------|------------|-----------|")
        for b in bearings[-15:]:
            bearing_str = f"{b['bearing']:.0f}°" if b["bearing"] is not None else "N/A"
            lines.append(
                f"| {b['time']} | {b['freq']} | {bearing_str} | {b.get('confidence', '')} |"
            )
        lines.append("")

        # If multiple bearings on same freq, note possible triangulation
        bearing_freqs = Counter(b["freq"] for b in bearings if b["freq"])
        multi = {f: c for f, c in bearing_freqs.items() if c >= 2}
        if multi:
            lines.append("**Triangulation candidates** (2+ bearings on same freq):")
            for f, c in multi.items():
                fb = [
                    b for b in bearings if b["freq"] == f and b["bearing"] is not None
                ]
                bearing_vals = [b["bearing"] for b in fb]
                lines.append(
                    f"  - {f} MHz: {c} bearings ({min(bearing_vals):.0f}° – {max(bearing_vals):.0f}°)"
                )
            lines.append("")

        lines.append("---")
        lines.append("")

    # ── Baseline Diff
    if baseline_diff_text:
        lines.append("## Baseline Comparison")
        lines.append("")
        lines.append("```")
        # Truncate if very long
        if len(baseline_diff_text) > 3000:
            lines.append(baseline_diff_text[:3000])
            lines.append("... (truncated)")
        else:
            lines.append(baseline_diff_text)
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    # ── Recommendations
    lines.append("## Analyst Recommendations")
    lines.append("")
    recommendations = []

    if bursts:
        freq_counter_b = Counter(b["freq"] for b in bursts if b["freq"])
        top_freq = freq_counter_b.most_common(1)
        if top_freq:
            recommendations.append(
                f"- [ ] Prioritize collection on **{top_freq[0][0]} MHz** ({top_freq[0][1]} bursts)"
            )

    if bearings:
        multi = {
            f: c
            for f, c in Counter(b["freq"] for b in bearings if b["freq"]).items()
            if c >= 2
        }
        for f in multi:
            recommendations.append(f"- [ ] Attempt triangulation fix on **{f} MHz**")

    if total_alerts > 10:
        recommendations.append(
            "- [ ] Consider tightening squelch threshold (high alert volume)"
        )

    if not recommendations:
        recommendations.append("- [ ] Continue baseline collection")
        recommendations.append("- [ ] Expand frequency coverage if resources permit")

    lines.extend(recommendations)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Report generated by sigint-field-kit intel_packager.py*  ")
    lines.append("*Source data should be retained per collection SOP*")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Intel packager — generates one-page SIGINT intelligence summary",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --bursts ~/SIGINT/logs/bursts.csv
  %(prog)s --bursts bursts.csv --alerts alerts.csv -o intel_report.md
  %(prog)s --all ~/SIGINT/logs/ --title "OP WATCHDOG" --location "Grid EN82"
  %(prog)s --bursts b.csv --bearings df.csv --baseline-diff diff.txt

Pipeline:
  burst_detector.py → baseline_diff.py → intel_packager.py → disseminate
        """,
    )
    parser.add_argument(
        "--bursts", type=str, default=None, help="Path to burst_detector CSV output"
    )
    parser.add_argument(
        "--alerts", type=str, default=None, help="Path to signal_alerter CSV output"
    )
    parser.add_argument(
        "--bearings",
        type=str,
        default=None,
        help="Path to DF bearings CSV (timestamp,freq,bearing_deg,confidence)",
    )
    parser.add_argument(
        "--baseline-diff",
        dest="baseline_diff",
        type=str,
        default=None,
        help="Path to baseline_diff.py text report",
    )
    parser.add_argument(
        "--all",
        type=str,
        default=None,
        help="Auto-discover all log files in this directory",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Operation name/title for the report header",
    )
    parser.add_argument(
        "--location",
        type=str,
        default=None,
        help="Collection location (grid square, coords, description)",
    )

    args = parser.parse_args()

    # Auto-discover mode
    if args.all:
        discovered = auto_discover_logs(args.all)
        if not args.bursts and "bursts" in discovered:
            args.bursts = str(discovered["bursts"])
        if not args.alerts and "alerts" in discovered:
            args.alerts = str(discovered["alerts"])
        if not args.bearings and "bearings" in discovered:
            args.bearings = str(discovered["bearings"])
        if not args.baseline_diff and "baseline_diff" in discovered:
            args.baseline_diff = str(discovered["baseline_diff"])

        if discovered:
            print(
                f"[INFO] Auto-discovered: {', '.join(discovered.keys())}",
                file=sys.stderr,
            )
        else:
            print(f"[WARN] No log files found in {args.all}", file=sys.stderr)

    # Check we have at least something to report on
    if not any([args.bursts, args.alerts, args.bearings, args.baseline_diff]):
        print(
            "[ERROR] No input data specified. Use --bursts, --alerts, --bearings, --baseline-diff, or --all.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parse inputs
    bursts = parse_bursts_csv(args.bursts)
    alerts = parse_alerts_csv(args.alerts)
    bearings = parse_bearings_csv(args.bearings)
    baseline_diff_text = read_baseline_diff(args.baseline_diff)

    # Generate report
    report = generate_report(bursts, alerts, bearings, baseline_diff_text, args)

    # Output
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[OK] Intel report written to {args.output}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
