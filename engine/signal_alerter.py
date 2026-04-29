#!/usr/bin/env python3
"""
Signal alerter — monitors a frequency and fires alerts on activity.

Watches an RTL-SDR for signals above threshold and triggers:
  - Desktop notification (notify-send)
  - Audible beep (optional)
  - Log entry with timestamp + power level
  - Webhook/command execution (optional)

Ideal for unattended monitoring with wake-on-signal awareness.
F3EAD: FIND/FIX phase — know when a target frequency goes active.

Requires: RTL-SDR dongle, rtl_power (part of rtl-sdr package)

Usage:
    ./signal_alerter.py -f 462.5625              # alert on FRS Ch1 activity
    ./signal_alerter.py -f 146.52 -s -35         # VHF, tight threshold
    ./signal_alerter.py -f 433.92 --beep         # ISM + audible alert
    ./signal_alerter.py -f 915 --command "echo LORA >> /tmp/hits.log"
"""

import argparse
import os
import shutil
import signal as sig
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


class SignalAlerter:
    def __init__(self, args):
        self.freq = args.freq
        self.threshold = args.threshold
        self.gain = args.gain
        self.interval = args.interval
        self.cooldown = args.cooldown
        self.beep = args.beep
        self.command = args.command
        self.logfile = args.log
        self.quiet = args.quiet
        self.device = getattr(args, "device", 0) or 0
        self.json_events = getattr(args, "json_events", False)

        self._running = True
        self._last_alert_time = 0
        self._alert_count = 0
        self._scan_count = 0

        # Validate rtl_power
        if not shutil.which("rtl_power"):
            print("[FATAL] rtl_power not found. Install rtl-sdr.", file=sys.stderr)
            sys.exit(1)

        # Validate notify-send (optional)
        self._has_notify = shutil.which("notify-send") is not None

        # Open log file
        self._log_fh = None
        if self.logfile:
            log_path = Path(self.logfile)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            write_header = not log_path.exists()
            self._log_fh = open(log_path, "a")
            if write_header:
                self._log_fh.write(
                    "timestamp_utc,freq_mhz,power_db,threshold_db,alert_num\n"
                )
                self._log_fh.flush()

    def run(self):
        """Main monitoring loop."""
        print("╔═══════════════════════════════════════════════╗")
        print("║  Signal Alerter                               ║")
        print("╠═══════════════════════════════════════════════╣")
        print(f"║  Freq:      {self.freq:>9.4f} MHz                   ║")
        print(f"║  Threshold: {self.threshold:>9.1f} dB                    ║")
        print(f"║  Cooldown:  {self.cooldown:>9.0f} s                     ║")
        print(f"║  Interval:  {self.interval:>9.1f} s                     ║")
        print(
            f"║  Beep:      {'ON' if self.beep else 'OFF':>9}                       ║"
        )
        notify_str = "ON" if self._has_notify else "N/A"
        print(f"║  Notify:    {notify_str:>9}                       ║")
        print("╚═══════════════════════════════════════════════╝")
        print("Watching for signals... Ctrl+C to stop.\n")

        while self._running:
            try:
                power = self._measure_power()
                self._scan_count += 1

                if power is not None:
                    now = time.time()
                    ts = datetime.now().strftime("%H:%M:%S")

                    if power > self.threshold:
                        # Check cooldown
                        if now - self._last_alert_time >= self.cooldown:
                            self._fire_alert(power)
                            self._last_alert_time = now
                        elif not self.quiet:
                            print(
                                f"[{ts}] Signal {power:.1f} dB (cooldown active)",
                                flush=True,
                            )
                    elif not self.quiet:
                        print(
                            f"[{ts}] scan #{self._scan_count:>4d}  power={power:.1f} dB  (below threshold)",
                            flush=True,
                        )

                time.sleep(self.interval)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[ERROR] {e}", file=sys.stderr, flush=True)
                time.sleep(5)

        self._shutdown()

    def _measure_power(self):
        """Single power measurement at target frequency using rtl_power."""
        # rtl_power needs a range; use a narrow window around target
        bw = 100000  # 100 kHz window
        freq_hz = int(self.freq * 1e6)
        f_low = freq_hz - bw // 2
        f_high = freq_hz + bw // 2

        cmd = [
            "rtl_power",
            "-f",
            f"{f_low}:{f_high}:{bw}",
            "-i",
            "1",
            "-g",
            str(self.gain),
            "-d",
            str(self.device),
            "-1",  # single shot
            "-",  # output to stdout
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                return None

            # Parse rtl_power CSV output: date,time,hz_low,hz_high,hz_step,samples,dB_values...
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.strip().split(",")
                if len(parts) > 6:
                    powers = []
                    for p in parts[6:]:
                        try:
                            powers.append(float(p.strip()))
                        except ValueError:
                            continue
                    if powers:
                        return max(powers)  # peak power in the window
            return None

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def _fire_alert(self, power):
        """Trigger all alert mechanisms."""
        self._alert_count += 1
        ts = datetime.now().strftime("%H:%M:%S")
        ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # Console alert
        print(
            f"[{ts}] *** ALERT #{self._alert_count} *** "
            f"Signal detected: {power:.1f} dB @ {self.freq:.4f} MHz",
            flush=True,
        )

        # Desktop notification
        if self._has_notify:
            try:
                subprocess.Popen(
                    [
                        "notify-send",
                        "--urgency=critical",
                        f"RF ALERT — {self.freq} MHz",
                        f"Signal: {power:.1f} dB (threshold: {self.threshold:.1f} dB)\n"
                        f"Alert #{self._alert_count} at {ts}",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

        # Audible beep
        if self.beep:
            try:
                # Try multiple beep methods
                if shutil.which("paplay"):
                    subprocess.Popen(
                        [
                            "paplay",
                            "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                elif shutil.which("aplay"):
                    # Generate a quick beep via aplay
                    subprocess.Popen(
                        ["bash", "-c", "echo -ne '\\a'"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    print("\a", end="", flush=True)  # terminal bell
            except Exception:
                print("\a", end="", flush=True)

        # Log to file
        if self._log_fh:
            self._log_fh.write(
                f"{ts_utc},{self.freq:.4f},{power:.1f},{self.threshold:.1f},{self._alert_count}\n"
            )
            self._log_fh.flush()

        # Custom command
        if self.command:
            try:
                env = os.environ.copy()
                env["ALERT_FREQ"] = f"{self.freq}"
                env["ALERT_POWER"] = f"{power:.1f}"
                env["ALERT_NUM"] = str(self._alert_count)
                env["ALERT_TIME"] = ts_utc
                subprocess.Popen(
                    self.command,
                    shell=True,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                print(f"[WARN] Command failed: {e}", file=sys.stderr)

        # JSON event line (for capture_service integration)
        if self.json_events:
            import json

            event = {
                "event_type": "alert",
                "timestamp": ts_utc,
                "freq_mhz": self.freq,
                "power_db": round(power, 1),
                "threshold_db": self.threshold,
                "alert_num": self._alert_count,
            }
            print(json.dumps(event), flush=True)

    def _shutdown(self):
        """Clean shutdown."""
        print(f"\n[STOP] {self._alert_count} alert(s) in {self._scan_count} scans.")
        if self._log_fh:
            self._log_fh.close()
        if self._alert_count > 0 and self.logfile:
            print(f"  Log: {self.logfile}")


def main():
    parser = argparse.ArgumentParser(
        description="Signal alerter — monitors frequency and fires alerts on activity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -f 462.5625                      Alert on FRS Ch1
  %(prog)s -f 146.52 -s -35 --beep         VHF voice + audible
  %(prog)s -f 433.92 --cooldown 60         ISM, max 1 alert/min
  %(prog)s -f 915 --command "./record.sh"  LoRa + trigger script

Custom commands receive environment variables:
  ALERT_FREQ, ALERT_POWER, ALERT_NUM, ALERT_TIME

Chain with other tools:
  %(prog)s -f 433.92 --command "python3 scripts/squelch_recorder.py -f 433.92 --max 30"
        """,
    )
    parser.add_argument(
        "-f", "--freq", type=float, required=True, help="Target frequency in MHz"
    )
    parser.add_argument(
        "-s",
        "--threshold",
        type=float,
        default=-40,
        help="Alert threshold in dB (default: -40)",
    )
    parser.add_argument(
        "-g", "--gain", type=float, default=38, help="RF gain (default: 38)"
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=5,
        help="Scan interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=30,
        help="Minimum seconds between alerts (default: 30)",
    )
    parser.add_argument("--beep", action="store_true", help="Play audible alert sound")
    parser.add_argument(
        "--command",
        type=str,
        default=None,
        help="Shell command to execute on alert (receives env vars)",
    )
    parser.add_argument(
        "--log",
        type=str,
        default=os.path.expanduser("~/SIGINT/logs/alerts.csv"),
        help="Alert log CSV path (default: ~/SIGINT/logs/alerts.csv)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only print alerts, suppress routine scan output",
    )
    parser.add_argument(
        "-d", "--device", type=int, default=0, help="RTL-SDR device index (default: 0)"
    )
    parser.add_argument(
        "--json-events",
        dest="json_events",
        action="store_true",
        help="Emit JSON event lines on stdout for integration",
    )

    args = parser.parse_args()

    alerter = SignalAlerter(args)

    def handle_sigint(signum, frame):
        alerter._running = False

    sig.signal(sig.SIGINT, handle_sigint)
    sig.signal(sig.SIGTERM, handle_sigint)

    alerter.run()


if __name__ == "__main__":
    main()
