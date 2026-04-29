#!/usr/bin/env python3
"""
Squelch-triggered IQ recorder.

Monitors a frequency and automatically records IQ samples to timestamped files
when signal power exceeds the squelch threshold. Ideal for unattended LP/OP
signal collection — walk away, come back to captures.

Requires: RTL-SDR dongle, GNU Radio + gr-osmosdr

Usage:
    ./squelch_recorder.py                          # defaults: 433.92 MHz, -40 dB
    ./squelch_recorder.py -f 146.52 -s -35         # VHF voice, tighter squelch
    ./squelch_recorder.py -f 915 -s -50 -o /tmp    # LoRa band, custom output dir
    ./squelch_recorder.py --headless                # no GUI, pure headless LP/OP
"""
import argparse
import os
import sys
import time
import signal as sig
from datetime import datetime, timezone
from pathlib import Path

try:
    from gnuradio import gr, blocks, analog, filter as grfilter
    from gnuradio.filter import firdes
    import osmosdr
except ImportError:
    print("[FATAL] GNU Radio not found. Install gnuradio + gr-osmosdr.", file=sys.stderr)
    sys.exit(1)

# ── Probe-triggered file sink ─────────────────────────────────────────────
# GNU Radio doesn't have a built-in "record only when signal present" block.
# We use a power probe + a Python callback that swaps file sinks in/out.

class SquelchRecorder(gr.top_block):
    def __init__(self, args):
        gr.top_block.__init__(self, "Squelch Recorder")

        self.freq = args.freq * 1e6
        self.samp_rate = int(args.rate * 1e6)
        self.squelch_db = args.squelch
        self.gain = args.gain
        self.outdir = Path(args.output)
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.min_duration = args.min_duration
        self.max_duration = args.max_duration

        self._recording = False
        self._rec_start = None
        self._current_sink = None
        self._current_file = None
        self._capture_count = 0

        # ── Source ──
        self.source = osmosdr.source(args="")
        self.source.set_sample_rate(self.samp_rate)
        self.source.set_center_freq(self.freq)
        self.source.set_gain(self.gain)
        self.source.set_if_gain(20)
        self.source.set_bb_gain(20)

        # ── Power probe (measures signal level) ──
        self.probe = analog.probe_avg_mag_sqrd_c(self.squelch_db, 0.001)

        # ── Null sink (default when not recording) ──
        self.null_sink = blocks.null_sink(gr.sizeof_gr_complex)

        # ── Valve to control data flow to file ──
        self.valve = blocks.copy(gr.sizeof_gr_complex)
        self.valve.set_enabled(False)

        # ── File sink placeholder ──
        self._null_file = blocks.null_sink(gr.sizeof_gr_complex)

        # ── Connect ──
        self.connect(self.source, self.probe)
        self.connect(self.source, self.valve)
        self.connect(self.valve, self._null_file)

        # ── Periodic check thread ──
        import threading
        self._running = True
        self._monitor = threading.Thread(target=self._monitor_loop, daemon=True)

    def start(self, *a, **kw):
        super().start(*a, **kw)
        self._monitor.start()

    def stop(self):
        self._running = False
        if self._recording:
            self._stop_recording()
        super().stop()

    def _monitor_loop(self):
        """Poll power probe and toggle recording."""
        while self._running:
            try:
                level = self.probe.level()
                power_db = 10 * (level + 1e-30).__log10__() if hasattr(level, '__log10__') else \
                           10 * __import__('math').log10(max(level, 1e-30))

                now = time.time()

                if not self._recording and power_db > self.squelch_db:
                    self._start_recording()
                elif self._recording:
                    elapsed = now - self._rec_start
                    if power_db <= self.squelch_db and elapsed >= self.min_duration:
                        self._stop_recording()
                    elif elapsed >= self.max_duration:
                        self._stop_recording()
                        self._log(f"Max duration {self.max_duration}s reached, splitting file")

                time.sleep(0.1)  # 100ms polling
            except Exception as e:
                self._log(f"Monitor error: {e}")
                time.sleep(1)

    def _start_recording(self):
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        freq_mhz = self.freq / 1e6
        fname = f"capture_{freq_mhz:.3f}MHz_{ts}_{self.samp_rate}sps.cf32"
        fpath = self.outdir / fname

        self.lock()
        try:
            self.disconnect(self.valve, self._null_file)
            self._current_sink = blocks.file_sink(gr.sizeof_gr_complex, str(fpath), False)
            self._current_sink.set_unbuffered(False)
            self.connect(self.valve, self._current_sink)
            self.valve.set_enabled(True)
        finally:
            self.unlock()

        self._recording = True
        self._rec_start = time.time()
        self._current_file = fpath
        self._capture_count += 1
        self._log(f"REC START → {fname}")

    def _stop_recording(self):
        elapsed = time.time() - self._rec_start if self._rec_start else 0

        self.lock()
        try:
            self.valve.set_enabled(False)
            if self._current_sink:
                self.disconnect(self.valve, self._current_sink)
                self._current_sink = None
            self._null_file = blocks.null_sink(gr.sizeof_gr_complex)
            self.connect(self.valve, self._null_file)
        finally:
            self.unlock()

        fsize = self._current_file.stat().st_size if self._current_file and self._current_file.exists() else 0
        self._log(f"REC STOP  → {elapsed:.1f}s, {fsize / 1024:.1f} KB")

        # Delete captures shorter than min_duration (noise triggers)
        if elapsed < self.min_duration and self._current_file and self._current_file.exists():
            self._current_file.unlink()
            self._log(f"  Deleted (shorter than {self.min_duration}s minimum)")
            self._capture_count -= 1

        self._recording = False
        self._rec_start = None
        self._current_file = None

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Squelch-triggered IQ recorder — auto-captures signals above threshold",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -f 433.92                    ISM band, default squelch
  %(prog)s -f 146.52 -s -35            VHF voice, tight squelch
  %(prog)s -f 915 -s -50 -r 2.4        LoRa band, 2.4 Msps
  %(prog)s -f 462.5625 --min 0.5       FRS Ch1, capture bursts >= 0.5s

Output files: <outdir>/capture_<freq>MHz_<timestamp>_<rate>sps.cf32
Open captures in URH, inspectrum, or GNU Radio for analysis.
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
    parser.add_argument("-o", "--output", type=str, default=os.path.expanduser("~/SIGINT/recordings"),
                        help="Output directory (default: ~/SIGINT/recordings)")
    parser.add_argument("--min", dest="min_duration", type=float, default=1.0,
                        help="Minimum capture duration in seconds; shorter = noise (default: 1.0)")
    parser.add_argument("--max", dest="max_duration", type=float, default=300,
                        help="Maximum capture duration in seconds before file split (default: 300)")
    parser.add_argument("--headless", action="store_true",
                        help="No GUI, pure console output for LP/OP deployment")

    args = parser.parse_args()

    print(f"╔═══════════════════════════════════════════════╗")
    print(f"║  Squelch-Triggered IQ Recorder                ║")
    print(f"╠═══════════════════════════════════════════════╣")
    print(f"║  Freq:     {args.freq:>10.4f} MHz                   ║")
    print(f"║  Squelch:  {args.squelch:>10.1f} dB                    ║")
    print(f"║  Gain:     {args.gain:>10.1f}                        ║")
    print(f"║  Rate:     {args.rate:>10.1f} Msps                   ║")
    print(f"║  Output:   {str(args.output):<35} ║")
    print(f"║  Min cap:  {args.min_duration:>10.1f} s                     ║")
    print(f"║  Max cap:  {args.max_duration:>10.1f} s                     ║")
    print(f"╚═══════════════════════════════════════════════╝")
    print(f"Monitoring... Ctrl+C to stop.\n")

    tb = SquelchRecorder(args)

    def handle_sigint(signum, frame):
        print(f"\n[STOP] Captured {tb._capture_count} file(s). Shutting down...")
        tb.stop()
        tb.wait()
        sys.exit(0)

    sig.signal(sig.SIGINT, handle_sigint)
    sig.signal(sig.SIGTERM, handle_sigint)

    tb.start()
    tb.wait()


if __name__ == "__main__":
    main()
