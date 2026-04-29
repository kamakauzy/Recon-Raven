#!/usr/bin/env python3
"""
Power logger — continuous RF power measurement over a frequency range.

Wraps rtl_power to produce time-series heatmap data. Runs unattended in
LP/OP mode, outputting CSV suitable for spectrogram visualization.

Generates data for: pattern-of-life analysis, new emitter detection,
spectrum occupancy studies. F3EAD FIND phase.

Requires: rtl_power (part of rtl-sdr package)

Usage:
    ./power_logger.py                              # defaults: 400-450 MHz
    ./power_logger.py -l 130 -u 170               # VHF range
    ./power_logger.py -l 900 -u 930 -b 50k        # LoRa band, fine resolution
    ./power_logger.py --duration 3600              # run for 1 hour
    ./power_logger.py --heatmap                    # generate heatmap plot at end
"""
import argparse
import csv
import math
import os
import signal as sig
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def validate_rtl_power():
    """Check that rtl_power is available."""
    try:
        result = subprocess.run(["rtl_power", "-h"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_power_scan(args):
    """Run rtl_power and process output in real-time."""
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    csv_file = outdir / f"power_{args.lower}-{args.upper}MHz_{ts}.csv"
    summary_file = outdir / f"power_{args.lower}-{args.upper}MHz_{ts}_summary.txt"

    freq_range = f"{int(args.lower * 1e6)}:{int(args.upper * 1e6)}:{args.bin_size}"
    interval = str(args.interval)

    cmd = [
        "rtl_power",
        "-f", freq_range,
        "-i", interval,
        "-g", str(args.gain),
        "-p", str(args.ppm),
        "-1",  # single-shot per interval (we loop externally for control)
    ]

    print(f"╔═══════════════════════════════════════════════╗")
    print(f"║  Power Logger                                 ║")
    print(f"╠═══════════════════════════════════════════════╣")
    print(f"║  Range:     {args.lower:>7.1f} - {args.upper:<7.1f} MHz            ║")
    print(f"║  Bin size:  {args.bin_size:>10}                      ║")
    print(f"║  Interval:  {args.interval:>10}s                     ║")
    print(f"║  Gain:      {args.gain:>10.1f}                       ║")
    print(f"║  Duration:  {args.duration:>10}s                     ║")
    print(f"║  Output:    {str(csv_file.name):<35}║")
    print(f"╚═══════════════════════════════════════════════╝")
    print(f"Logging power data... Ctrl+C to stop.\n")

    # Use continuous mode with file output
    cmd_continuous = [
        "rtl_power",
        "-f", freq_range,
        "-i", interval,
        "-g", str(args.gain),
        "-p", str(args.ppm),
    ]

    if args.duration > 0:
        cmd_continuous.extend(["-e", f"{args.duration}s"])

    # rtl_power outputs CSV to stdout or file
    cmd_continuous.extend([str(csv_file)])

    scan_count = 0
    peak_power = -999
    start_time = time.time()
    process = None

    def handle_sigint(signum, frame):
        nonlocal process
        elapsed = time.time() - start_time
        print(f"\n[STOP] Logged {scan_count} sweeps over {elapsed:.0f}s")
        print(f"  Peak power: {peak_power:.1f} dB")
        print(f"  Output: {csv_file}")
        if process:
            process.terminate()
        write_summary(summary_file, args, scan_count, elapsed, peak_power, csv_file)
        if args.heatmap:
            generate_heatmap(csv_file)
        sys.exit(0)

    sig.signal(sig.SIGINT, handle_sigint)
    sig.signal(sig.SIGTERM, handle_sigint)

    try:
        process = subprocess.Popen(
            cmd_continuous,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Monitor progress by watching file growth
        last_size = 0
        while process.poll() is None:
            time.sleep(args.interval)
            if csv_file.exists():
                current_size = csv_file.stat().st_size
                if current_size > last_size:
                    scan_count += 1
                    last_size = current_size
                    elapsed = time.time() - start_time
                    # Read last line for peak info
                    try:
                        with open(csv_file, "r") as f:
                            for line in f:
                                pass  # get last line
                            if line:
                                parts = line.strip().split(",")
                                # rtl_power CSV: date,time,hz_low,hz_high,hz_step,samples,dB...
                                if len(parts) > 6:
                                    powers = [float(p) for p in parts[6:] if p.strip()]
                                    if powers:
                                        sweep_peak = max(powers)
                                        if sweep_peak > peak_power:
                                            peak_power = sweep_peak
                    except (ValueError, IOError):
                        pass

                    ts_now = datetime.now().strftime("%H:%M:%S")
                    print(f"[{ts_now}] Sweep #{scan_count:>4d}  "
                          f"elapsed={elapsed:.0f}s  peak={peak_power:.1f}dB",
                          flush=True)

        # Process finished
        elapsed = time.time() - start_time
        print(f"\n[DONE] Completed {scan_count} sweeps over {elapsed:.0f}s")
        print(f"  Output: {csv_file}")
        write_summary(summary_file, args, scan_count, elapsed, peak_power, csv_file)

        if args.heatmap:
            generate_heatmap(csv_file)

    except FileNotFoundError:
        print("[FATAL] rtl_power not found. Install rtl-sdr package.", file=sys.stderr)
        sys.exit(1)


def write_summary(summary_file, args, scan_count, elapsed, peak_power, csv_file):
    """Write a human-readable summary alongside the CSV."""
    with open(summary_file, "w") as f:
        f.write(f"Power Logger Summary\n")
        f.write(f"{'=' * 40}\n")
        f.write(f"Range:     {args.lower} - {args.upper} MHz\n")
        f.write(f"Bin size:  {args.bin_size}\n")
        f.write(f"Interval:  {args.interval}s\n")
        f.write(f"Gain:      {args.gain}\n")
        f.write(f"Sweeps:    {scan_count}\n")
        f.write(f"Duration:  {elapsed:.0f}s\n")
        f.write(f"Peak:      {peak_power:.1f} dB\n")
        f.write(f"Data file: {csv_file}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")


def generate_heatmap(csv_file):
    """Generate a spectrogram/heatmap image from rtl_power CSV."""
    try:
        import numpy as np
    except ImportError:
        print("[WARN] numpy not available, skipping heatmap generation", file=sys.stderr)
        return

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[WARN] matplotlib not available, skipping heatmap generation", file=sys.stderr)
        return

    print("[INFO] Generating heatmap...")

    # Parse rtl_power CSV
    times = []
    freq_bins = None
    power_data = []

    with open(csv_file, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 7:
                continue
            try:
                date_str = row[0]
                time_str = row[1]
                hz_low = float(row[2])
                hz_high = float(row[3])
                hz_step = float(row[4])
                # row[5] = num_samples
                powers = [float(p) for p in row[6:]]

                if freq_bins is None:
                    n_bins = len(powers)
                    freq_bins = np.linspace(hz_low / 1e6, hz_high / 1e6, n_bins)

                times.append(f"{date_str} {time_str}")
                power_data.append(powers)
            except (ValueError, IndexError):
                continue

    if not power_data:
        print("[WARN] No data to plot", file=sys.stderr)
        return

    # Create heatmap
    data = np.array(power_data)
    fig, ax = plt.subplots(figsize=(14, 6))
    im = ax.imshow(
        data.T, aspect="auto", origin="lower",
        extent=[0, len(times), freq_bins[0], freq_bins[-1]],
        cmap="inferno", vmin=-60, vmax=-10
    )
    ax.set_xlabel("Sweep #")
    ax.set_ylabel("Frequency (MHz)")
    ax.set_title(f"RF Power Heatmap — {csv_file.name}")
    plt.colorbar(im, ax=ax, label="Power (dB)")
    plt.tight_layout()

    img_file = csv_file.with_suffix(".png")
    plt.savefig(img_file, dpi=150)
    plt.close()
    print(f"[OK] Heatmap saved: {img_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Power logger — continuous RF power sweep over frequency range",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -l 430 -u 440                   ISM 433 band
  %(prog)s -l 144 -u 148 -b 25k           2m amateur band, fine bins
  %(prog)s -l 900 -u 930 --duration 7200   LoRa band, 2 hours
  %(prog)s -l 460 -u 470 --heatmap         UHF + generate spectrogram

Output: CSV compatible with rtl_power format. Use --heatmap to auto-generate
a spectrogram image (requires numpy + matplotlib).

Feed data into baseline_diff.py for change detection.
        """,
    )
    parser.add_argument("-l", "--lower", type=float, default=400,
                        help="Lower frequency bound in MHz (default: 400)")
    parser.add_argument("-u", "--upper", type=float, default=450,
                        help="Upper frequency bound in MHz (default: 450)")
    parser.add_argument("-b", "--bin-size", dest="bin_size", type=str, default="100k",
                        help="Frequency bin size (default: 100k)")
    parser.add_argument("-i", "--interval", type=float, default=10,
                        help="Sweep interval in seconds (default: 10)")
    parser.add_argument("-g", "--gain", type=float, default=38,
                        help="RF gain (default: 38)")
    parser.add_argument("-p", "--ppm", type=int, default=0,
                        help="Frequency correction in ppm (default: 0)")
    parser.add_argument("-d", "--duration", type=int, default=0,
                        help="Total duration in seconds, 0=infinite (default: 0)")
    parser.add_argument("-o", "--output", type=str,
                        default=os.path.expanduser("~/SIGINT/logs"),
                        help="Output directory (default: ~/SIGINT/logs)")
    parser.add_argument("--heatmap", action="store_true",
                        help="Generate heatmap image after completion (needs numpy+matplotlib)")

    args = parser.parse_args()

    if not validate_rtl_power():
        print("[FATAL] rtl_power not found in PATH. Install rtl-sdr.", file=sys.stderr)
        sys.exit(1)

    if args.lower >= args.upper:
        print("[ERROR] Lower freq must be less than upper freq", file=sys.stderr)
        sys.exit(1)

    run_power_scan(args)


if __name__ == "__main__":
    main()
