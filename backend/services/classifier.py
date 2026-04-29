"""
Signal classifier — rule-based + ML pipeline for auto-classifying detected signals.
"""
import fnmatch
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger("raven.classifier")


class ClassificationResult:
    __slots__ = ("label", "confidence", "method", "rule_name", "features")

    def __init__(self, label: str, confidence: float, method: str = "rule",
                 rule_name: str = "", features: dict = None):
        self.label = label
        self.confidence = confidence
        self.method = method
        self.rule_name = rule_name
        self.features = features or {}

    def to_dict(self):
        return {
            "label": self.label,
            "confidence": self.confidence,
            "method": self.method,
            "rule_name": self.rule_name,
        }


class ClassificationRule:
    """A single YAML-defined classification rule."""

    def __init__(self, data: dict, filename: str):
        self.name = data.get("name", filename)
        self.match = data.get("match", {})
        self.models = data.get("models", [])
        self.priority = data.get("priority", 50)
        self.description = data.get("description", "")
        self._filename = filename

    def evaluate(self, event: dict) -> Optional[Tuple[float, str]]:
        """
        Evaluate this rule against an event.
        Returns (confidence, label) or None if no match.
        """
        score = 0
        checks = 0

        # Frequency range check
        freq_ranges = self.match.get("freq_range", [])
        freq = event.get("freq_mhz", 0)
        if freq_ranges and freq:
            if self._in_ranges(freq, freq_ranges):
                score += 30
            else:
                return None  # Hard fail — wrong frequency band
            checks += 1

        # Duration check
        dur_range = self.match.get("burst_duration_range")
        dur = event.get("duration_ms")
        if dur_range and dur is not None:
            if len(dur_range) == 2 and dur_range[0] <= dur <= dur_range[1]:
                score += 25
            else:
                score -= 15
            checks += 1

        # rtl_433 model name match (strongest indicator)
        model_str = event.get("model", "")
        if model_str and self.models:
            for pattern in self.models:
                if fnmatch.fnmatch(model_str, pattern):
                    score += 40
                    break
            checks += 1

        # Modulation match
        mods = self.match.get("modulation", [])
        event_mod = event.get("modulation", "")
        if mods and event_mod:
            if event_mod.upper() in [m.upper() for m in mods]:
                score += 20
            checks += 1

        # Bandwidth check
        bw_range = self.match.get("bandwidth_khz_range")
        bw = event.get("bandwidth_khz")
        if bw_range and bw is not None:
            if len(bw_range) == 2 and bw_range[0] <= bw <= bw_range[1]:
                score += 15
            checks += 1

        if checks == 0:
            return None

        # Normalize confidence to 0-1
        max_possible = checks * 30  # rough max per check
        confidence = min(1.0, max(0.0, score / max(max_possible, 1)))

        if confidence < 0.2:
            return None

        return (confidence, self.name)

    @staticmethod
    def _in_ranges(freq: float, ranges: list) -> bool:
        """Check if freq falls in any of the specified ranges.
        Ranges can be [low1, high1, low2, high2, ...] pairs."""
        if len(ranges) % 2 != 0:
            # Single values — check within ±2 MHz
            for r in ranges:
                if abs(freq - r) <= 2.0:
                    return True
            return False

        for i in range(0, len(ranges), 2):
            if ranges[i] <= freq <= ranges[i+1]:
                return True
        return False


class Classifier:
    """Signal classification engine — rules first, ML fallback."""

    def __init__(self, rules_dir: str = None):
        self._rules: List[ClassificationRule] = []
        self._ml_model = None

        if rules_dir:
            self._load_rules(rules_dir)

    def _load_rules(self, rules_dir: str):
        """Load all YAML rule files from the rules directory."""
        rules_path = Path(rules_dir)
        if not rules_path.exists():
            logger.warning("Rules directory not found: %s", rules_dir)
            return

        for yml_file in sorted(rules_path.glob("*.yml")):
            try:
                with open(yml_file) as f:
                    data = yaml.safe_load(f)
                if data:
                    rule = ClassificationRule(data, yml_file.stem)
                    self._rules.append(rule)
            except Exception as e:
                logger.error("Failed to load rule %s: %s", yml_file, e)

        # Sort by priority (lower = higher priority)
        self._rules.sort(key=lambda r: r.priority)
        logger.info("Loaded %d classification rule(s)", len(self._rules))

    def classify(self, event: dict) -> ClassificationResult:
        """
        Classify a signal event.
        Tries rules first (fast), then ML if no rule matches.
        """
        # 1. Try rule-based classification
        best_match = None
        best_confidence = 0

        for rule in self._rules:
            result = rule.evaluate(event)
            if result and result[0] > best_confidence:
                best_confidence = result[0]
                best_match = (result[1], rule._filename)

        if best_match and best_confidence >= 0.3:
            return ClassificationResult(
                label=best_match[0],
                confidence=round(best_confidence, 2),
                method="rule",
                rule_name=best_match[1],
            )

        # 2. Try ML classification (if model loaded)
        if self._ml_model:
            return self._classify_ml(event)

        # 3. Unknown
        return ClassificationResult(
            label="Unknown",
            confidence=0.0,
            method="none",
        )

    def _classify_ml(self, event: dict) -> ClassificationResult:
        """ML-based classification stub — placeholder for trained model."""
        # TODO: implement when training data is available
        return ClassificationResult(
            label="Unknown",
            confidence=0.0,
            method="ml",
        )

    def load_ml_model(self, model_path: str):
        """Load a trained ML model for classification."""
        try:
            import joblib
            self._ml_model = joblib.load(model_path)
            logger.info("ML model loaded: %s", model_path)
        except Exception as e:
            logger.warning("Failed to load ML model: %s", e)

    @property
    def rule_count(self):
        return len(self._rules)

    def list_rules(self):
        """List all loaded rules."""
        return [
            {
                "name": r.name,
                "priority": r.priority,
                "description": r.description,
                "models": r.models,
            }
            for r in self._rules
        ]
