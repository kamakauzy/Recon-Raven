#!/usr/bin/env python3
"""
Burst detector — detects, timestamps, and logs short RF bursts.

Monitors a frequency band and detects signal bursts that exceed the power
threshold. Logs each burst with timestamp, duration, peak power, and
estimated bandwidth. Optionally records IQ data for each burst.

Designed for detecting LoRa packets, FSK data bursts, sensor transmissions,
and other intermittent signals that form pattern-of-life.

Requires: RTL-SDR dongle, GNU Radio + gr-osmosdr

Usage:
    ./burst_detector.py                            # defaults: 433.92 MHz
    ./burst_detector.py -f 915 -s -45              # LoRa band
    ./burst_detector.py -f 433.92 --record         # also capture IQ per burst
    ./burst_detector.py -f 462.5625 --log bursts.csv
"""
import argparse
import csv
import math
import os
import sys
import time
import signal as sig
import threading
from datetime import datetime, timezone
from pathlib import Path

try:
    from gnuradio import gr, blocks, analog
    import osmosdr
except ImportError:
    print("[FATAL] GNU Radio not found. Install gnuradio + gr-osmosdr.", file=sys.stderr)
    sys.exit(1)


class BurstDetector(gr.top_block):
    def __init__(self, args):
        gr.top_block.__init__(self, "Burst Detector")

        self.freq = args.freq * 1e6
        self.samp_rate = int(args.rate * 1e6)
        self.squelch_db = args.squelch
        self.gain = args.gain
        self.outdir = Path(args.output)
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.do_record = args.record
        self.min_burst = args.min_burst
        self.logfile = args.log

        self._bursts = []
        self._in_burst = False
        self._burst_start = None
        self._burst_peak = -999
        self._burst_count = 0

        # Recording state
        self._current_sink = None
        self._current_file = None

        self.json_events = getattr(args, 'json_events', False)

        # ── Source ──
        device_index = getattr(args, 'device', 0) or 0
        self.source = osmosdr.source(args=f"rtl={device_index}")
        self.source.set_sample_rate(self.samp_rate)
        self.source.set_center_freq(self.freq)
        self.source.set_gain(self.gain)
        self.source.set_if_gain(20)
        self.source.set_bb_gain(20)

        # ── Power probe ──
        self.probe = analog.probe_avg_mag_sqrd_c(self.squelch_db, 0.0005)

        # ── Recording valve ──
        self.valve = blocks.copy(gr.sizeof_gr_complex)
        self.valve.set_enabled(False)
        self._null_sink = blocks.null_sink(gr.sizeof_gr_complex)

        # ── Connect ──
        self.connect(self.source, self.probe)
        self.connect(self.source, self.valve)
        self.connect(self.valve, self._null_sink)

        # ── Monitor thread ──
        self._running = True
        self._monitor = threading.Thread(target=self._monitor_loop, daemon=True)

        # ── CSV log ──
        self._csv_file = None
        self._csv_writer = None
        if self.logfile:
            log_path = Path(self.logfile)
            write_header = not log_path.exists()
            self._csv_file = open(log_path, "a", newline="")
            self._csv_writer = csv.writer(self._csv_file)
            if write_header:
                self._csv_writer.writerow([
                    "timestamp_utc", "freq_mhz", "duration_ms",
                    "peak_power_db", "iq_file"
                ])

    def start(self, *a, **kw):
        super().start(*a, **kw)
        self._monitor.start()

    def stop(self):
        self._running = False
        if self._in_burst:
            self._end_burst()
        if self._csv_file:
            self._csv_file.close()
        super().stop()

    def _monitor_loop(self):
        while self._running:
            try:
                level = self.probe.level()
                power_db = 10 * math.log10(max(level, 1e-30))
                now = time.time()

                if not self._in_burst and power_db > self.squelch_db:
                    self._start_burst(power_db)
                elif self._in_burst:
                    if power_db > self._burst_peak:
                        self._burst_peak = power_db
                    if power_db <= self.squelch_db:
                        self._end_burst()
                    elif now - self._burst_start > 60:
                        # Safety: cap burst at 60s (continuous signal, not a burst)
                        self._end_burst()
                        self._log("  (Capped at 60s — likely continuous signal, not burst)")

                time.sleep(0.02)  # 20ms polling — fast enough for sub-100ms bursts
            except Exception as e:
                self._log(f"Monitor error: {e}")
                time.sleep(1)

    def _start_burst(self, power_db):
        self._in_burst = True
        self._burst_start = time.time()
        self._burst_peak = power_db

        if self.do_record:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")[:-3]
            freq_mhz = self.freq / 1e6
            fname = f"burst_{freq_mhz:.3f}MHz_{ts}.cf32"
            fpath = self.outdir / fname

            self.lock()
            try:
                self.disconnect(self.valve, self._null_sink)
                self._current_sink = blocks.file_sink(gr.sizeof_gr_complex, str(fpath), False)
                self._current_sink.set_unbuffered(True)
                self.connect(self.valve, self._current_sink)
                self.valve.set_enabled(True)
            finally:
                self.unlock()
            self._current_file = fpath

    def _end_burst(self):
        duration = time.time() - self._burst_start if self._burst_start else 0
        duration_ms = duration * 1000

        # Stop recording
        if self.do_record and self._current_sink:
            self.lock()
            try:
                self.valve.set_enabled(False)
                self.disconnect(self.valve, self._current_sink)
                self._current_sink = None
                self._null_sink = blocks.null_sink(gr.sizeof_gr_complex)
                self.connect(self.valve, self._null_sink)
            finally:
                self.unlock()

        iq_file = ""

        # Discard sub-minimum bursts
        if duration < self.min_burst:
            if self._current_file and self._current_file.exists():
                self._current_file.unlink()
        else:
            self._burst_count += 1
            ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            freq_mhz = self.freq / 1e6

            if self._current_file and self._current_file.exists():
                fsize = self._current_file.stat().st_size
                iq_file = self._current_file.name
                rec_info = f", IQ: {fsize / 1024:.1f} KB"
            else:
                rec_info = ""

            self._log(
                f"BURST #{self._burst_count:>4d}  "
                f"dur={duration_ms:>7.1f}ms  "
                f"peak={self._burst_peak:>6.1f}dB  "
                f"freq={freq_mhz:.3f}MHz"
                f"{rec_info}"
            )

            # CSV log
            if self._csv_writer:
                self._csv_writer.writerow([
                    ts_utc, f"{freq_mhz:.4f}",
                    f"{duration_ms:.1f}", f"{self._burst_peak:.1f}",
                    iq_file
                ])
                self._csv_file.flush()

            # JSON event line (for capture_service integration)
            if self.json_events:
                import json
                event = {
                    "event_type": "burst",
                    "timestamp": ts_utc,
                    "freq_mhz": freq_mhz,
                    "duration_ms": round(duration_ms, 1),
                    "peak_power_db": round(self._burst_peak, 1),
                    "iq_file": iq_file,
                    "burst_num": self._burst_count,
                }
                print(json.dumps(event), flush=True)

        self._in_burst = False
        self._burst_start = None
        self._burst_peak = -999
        self._current_file = None

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] {msg}", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Burst detector — detects, timestamps, and logs short RF bursts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -f 433.92                        ISM burst detection
  %(prog)s -f 915 -s -45 --record           LoRa + save IQ
  %(prog)s -f 433.92 --log ~/SIGINT/logs/bursts.csv
  %(prog)s -f 462.5625 --min-burst 0.01     FRS, catch 10ms+ bursts

Output CSV columns: timestamp_utc, freq_mhz, duration_ms, peak_power_db, iq_file
Feed the CSV into baseline_diff.py or intel_packager.py for F3EAD analysis.
        """,
    )
    parser.add_argument("-f", "--freq", type=float, default=433.92,
                        help="Center frequency in MHz (default: 433.92)")
    parser.add_argument("-s", "--squelch", type=float, default=-40,
                        help="Squelch threshold in dB (default: -40)")
    parser.add_argument("-g", "--gain", type=float, default=38,
                        help="RF gain (default: 38)")
    parser.add_argument("-r", "--rate", type=float, default=2.4,
                        help="Sample rate in Msps (default: 2.4)")
    parser.add_argument("-o", "--output", type=str,
                        default=os.path.expanduser("~/SIGINT/recordings"),
                        help="Output directory for IQ captures (default: ~/SIGINT/recordings)")
    parser.add_argument("--record", action="store_true",
                        help="Record IQ data for each burst")
    parser.add_argument("--log", type=str, default=None,
                        help="Append burst log to CSV file")
    parser.add_argument("--min-burst", dest="min_burst", type=float, default=0.02,
                        help="Minimum burst duration in seconds (default: 0.02)")
    parser.add_argument("-d", "--device", type=int, default=0,
                        help="RTL-SDR device index (default: 0)")
    parser.add_argument("--json-events", dest="json_events", action="store_true",
                        help="Emit JSON event lines on stdout for integration")

    args = parser.parse_args()

    # Default log file if not specified
    if args.log is None:
        args.log = os.path.expanduser("~/SIGINT/logs/bursts.csv")

    print(f"╔═══════════════════════════════════════════════╗")
    print(f"║  Burst Detector                               ║")
    print(f"╠═══════════════════════════════════════════════╣")
    print(f"║  Freq:      {args.freq:>9.4f} MHz                   ║")
    print(f"║  Squelch:   {args.squelch:>9.1f} dB                    ║")
    print(f"║  Min burst: {args.min_burst * 1000:>9.1f} ms                    ║")
    print(f"║  Recording: {'ON' if args.record else 'OFF':>9}                       ║")
    print(f"║  Log:       {str(args.log):<35}║")
    print(f"╚═══════════════════════════════════════════════╝")
    print(f"Monitoring for bursts... Ctrl+C to stop.\n")

    tb = BurstDetector(args)

    def handle_sigint(signum, frame):
        print(f"\n[STOP] Detected {tb._burst_count} burst(s). Shutting down...")
        tb.stop()
        tb.wait()
        sys.exit(0)

    sig.signal(sig.SIGINT, handle_sigint)
    sig.signal(sig.SIGTERM, handle_sigint)

    tb.start()
    tb.wait()


if __name__ == "__main__":
    main()
