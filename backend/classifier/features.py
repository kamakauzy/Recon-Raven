"""
Feature extraction from IQ captures for ML classification.

Extracts spectral and temporal features from cf32 IQ files.
"""

import logging
from pathlib import Path
from typing import Dict, Optional

import numpy as np

logger = logging.getLogger("raven.features")


def extract_features(iq_path: str, sample_rate: float = 2.4e6) -> Optional[Dict]:
    """
    Extract classification features from a cf32 IQ file.

    Returns dict with:
      - bandwidth_khz: estimated signal bandwidth
      - center_offset_khz: offset from center frequency
      - peak_power_db: peak power
      - avg_power_db: average power
      - duty_cycle: fraction of time signal is active
      - burst_count: number of distinct bursts
      - modulation_hint: estimated modulation type
      - symbol_rate_est: estimated symbol rate (Hz)
    """
    path = Path(iq_path)
    if not path.exists() or path.stat().st_size < 1024:
        return None

    try:
        # Read IQ data (complex float32 = 8 bytes per sample)
        raw = np.fromfile(str(path), dtype=np.complex64)
        if len(raw) < 512:
            return None

        # Limit to first 2M samples (avoid memory issues on large files)
        if len(raw) > 2_000_000:
            raw = raw[:2_000_000]

        features = {}

        # Power statistics
        power = np.abs(raw) ** 2
        power_db = 10 * np.log10(np.maximum(power, 1e-30))
        features["peak_power_db"] = round(float(np.max(power_db)), 1)
        features["avg_power_db"] = round(float(np.mean(power_db)), 1)
        features["std_power_db"] = round(float(np.std(power_db)), 1)

        # Bandwidth estimation via FFT
        fft_size = min(4096, len(raw))
        spectrum = np.fft.fftshift(np.abs(np.fft.fft(raw[:fft_size])))
        spectrum_db = 10 * np.log10(np.maximum(spectrum**2, 1e-30))
        noise_floor = np.median(spectrum_db)
        above_noise = spectrum_db > (noise_floor + 6)  # 6 dB above noise
        bw_bins = np.sum(above_noise)
        hz_per_bin = sample_rate / fft_size
        features["bandwidth_khz"] = round(float(bw_bins * hz_per_bin / 1000), 1)

        # Center offset
        peak_bin = np.argmax(spectrum_db)
        center_bin = fft_size // 2
        features["center_offset_khz"] = round(
            float((peak_bin - center_bin) * hz_per_bin / 1000), 1
        )

        # Duty cycle (fraction of samples above threshold)
        threshold = noise_floor + 10
        features["duty_cycle"] = round(float(np.mean(power_db > threshold)), 3)

        # Burst counting (simple threshold crossings)
        active = power_db > threshold
        transitions = np.diff(active.astype(int))
        features["burst_count"] = int(np.sum(transitions == 1))

        # Modulation hint from instantaneous frequency
        phase = np.angle(raw)
        inst_freq = np.diff(np.unwrap(phase)) * sample_rate / (2 * np.pi)

        freq_std = np.std(inst_freq)
        np.mean(np.abs(inst_freq))

        if freq_std < 1000:
            features["modulation_hint"] = "CW"
        elif freq_std < 5000:
            features["modulation_hint"] = "OOK"
        elif freq_std < 50000:
            features["modulation_hint"] = "FSK"
        else:
            features["modulation_hint"] = "wideband"

        # Symbol rate estimation (from autocorrelation of envelope)
        envelope = np.abs(raw[: min(100000, len(raw))])
        env_norm = envelope - np.mean(envelope)
        autocorr = np.correlate(env_norm[:4096], env_norm[:4096], mode="full")
        autocorr = autocorr[len(autocorr) // 2 :]

        # Find first significant peak after zero-lag
        if len(autocorr) > 100:
            autocorr_norm = autocorr / (autocorr[0] + 1e-30)
            peaks = []
            for i in range(10, len(autocorr_norm) - 1):
                if (
                    autocorr_norm[i] > autocorr_norm[i - 1]
                    and autocorr_norm[i] > autocorr_norm[i + 1]
                    and autocorr_norm[i] > 0.3
                ):
                    peaks.append(i)
                    break

            if peaks:
                features["symbol_rate_est"] = round(float(sample_rate / peaks[0]), 0)
            else:
                features["symbol_rate_est"] = 0
        else:
            features["symbol_rate_est"] = 0

        features["sample_count"] = len(raw)
        features["duration_ms"] = round(len(raw) / sample_rate * 1000, 1)

        return features

    except Exception as e:
        logger.error("Feature extraction failed for %s: %s", iq_path, e)
        return None
