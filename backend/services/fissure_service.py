"""
FISSURE integration — protocol DB queries, modulation detection, TX flowgraph launcher.

FISSURE (Frequency Independent SDR-based Signal Understanding and Reverse Engineering)
is an open-source RF analysis framework. This service wraps its protocol database
and flowgraph capabilities for integration with Recon-Raven.
"""
import asyncio
import csv
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("raven.fissure")


class FissureService:
    def __init__(self, settings):
        self._install_path = Path(settings.fissure.install_path)
        self._enabled = settings.fissure.enabled
        self._protocols: List[Dict] = []
        self._available = False

        if self._enabled:
            self._check_installation()
            if self._available:
                self._load_protocol_db()

    def _check_installation(self):
        """Verify FISSURE is installed."""
        if not self._install_path.exists():
            logger.warning("FISSURE not found at %s — integration disabled", self._install_path)
            self._available = False
            return

        # Check for key files
        lib_path = self._install_path / "Flow Graph Library"
        if lib_path.exists():
            self._available = True
            logger.info("FISSURE found at %s", self._install_path)
        else:
            logger.warning("FISSURE directory exists but Flow Graph Library not found")
            self._available = False

    def _load_protocol_db(self):
        """Load FISSURE protocol database from CSV files."""
        lib_path = self._install_path / "Flow Graph Library"

        # Try to load protocol data from various CSV files
        for csv_file in lib_path.glob("**/*.csv"):
            try:
                with open(csv_file, encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        protocol = {
                            "source_file": csv_file.stem,
                            "name": row.get("Protocol", row.get("protocol", row.get("Name", ""))),
                            "modulation": row.get("Modulation", row.get("modulation", "")),
                            "frequency": row.get("Frequency", row.get("frequency", "")),
                            "bandwidth": row.get("Bandwidth", row.get("bandwidth", "")),
                            "notes": row.get("Notes", row.get("notes", "")),
                        }
                        if protocol["name"]:
                            self._protocols.append(protocol)
            except Exception as e:
                logger.debug("Skipping %s: %s", csv_file, e)

        logger.info("Loaded %d FISSURE protocol entries", len(self._protocols))

    @property
    def available(self):
        return self._available

    def list_protocols(self, search: str = "") -> List[Dict]:
        """List protocols, optionally filtered by search term."""
        if not search:
            return self._protocols[:200]

        search_lower = search.lower()
        return [
            p for p in self._protocols
            if search_lower in p.get("name", "").lower()
            or search_lower in p.get("modulation", "").lower()
            or search_lower in p.get("frequency", "").lower()
        ][:200]

    def query_protocol(self, freq_mhz: float, modulation: str = "",
                       bandwidth_khz: float = 0) -> List[Dict]:
        """Query protocols matching given signal parameters."""
        matches = []
        for p in self._protocols:
            score = 0

            # Frequency match
            freq_str = p.get("frequency", "")
            if freq_str:
                try:
                    p_freq = float(freq_str.replace("MHz", "").replace("GHz", "").strip())
                    if "GHz" in freq_str:
                        p_freq *= 1000
                    if abs(p_freq - freq_mhz) < 5:  # within 5 MHz
                        score += 50
                except (ValueError, AttributeError):
                    pass

            # Modulation match
            if modulation and modulation.upper() in p.get("modulation", "").upper():
                score += 30

            if score > 0:
                matches.append({**p, "match_score": score})

        matches.sort(key=lambda x: x["match_score"], reverse=True)
        return matches[:20]

    def get_demod_flowgraphs(self, protocol: str = "") -> List[Dict]:
        """Find demodulation flowgraphs for a protocol."""
        if not self._available:
            return []

        lib_path = self._install_path / "Flow Graph Library"
        flowgraphs = []

        for grc in lib_path.rglob("*.grc"):
            if "demod" in grc.stem.lower() or "rx" in grc.stem.lower():
                if not protocol or protocol.lower() in grc.stem.lower():
                    flowgraphs.append({
                        "name": grc.stem,
                        "path": str(grc),
                        "type": "demodulation",
                    })

        for py in lib_path.rglob("*.py"):
            if "demod" in py.stem.lower() or "rx" in py.stem.lower():
                if not protocol or protocol.lower() in py.stem.lower():
                    flowgraphs.append({
                        "name": py.stem,
                        "path": str(py),
                        "type": "demodulation",
                    })

        return flowgraphs[:50]

    def get_attack_flowgraphs(self, protocol: str = "") -> List[Dict]:
        """Find TX/attack flowgraphs for a protocol."""
        if not self._available:
            return []

        lib_path = self._install_path / "Flow Graph Library"
        flowgraphs = []

        for py in lib_path.rglob("*.py"):
            if any(kw in py.stem.lower() for kw in ("tx", "attack", "mod", "replay", "jam")):
                if not protocol or protocol.lower() in py.stem.lower():
                    flowgraphs.append({
                        "name": py.stem,
                        "path": str(py),
                        "type": "attack",
                    })

        return flowgraphs[:50]

    async def run_modulation_detection(self, iq_file: str) -> Optional[Dict]:
        """Run FISSURE's TSI modulation detector on an IQ file."""
        if not self._available:
            return None

        # Look for TSI modulation detector script
        tsi_scripts = list((self._install_path / "Flow Graph Library").rglob("*modulation*detect*.py"))
        if not tsi_scripts:
            logger.warning("FISSURE TSI modulation detector not found")
            return None

        script = str(tsi_scripts[0])
        cmd = ["/usr/bin/python3", script, "--file", iq_file]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            output = stdout.decode(errors="replace")

            return {
                "script": script,
                "output": output,
                "iq_file": iq_file,
            }
        except asyncio.TimeoutError:
            return {"error": "Modulation detection timed out"}
        except Exception as e:
            return {"error": str(e)}

    async def launch_gui(self, context: dict = None) -> dict:
        """Launch FISSURE GUI with optional context."""
        if not self._available:
            return {"error": "FISSURE not available"}

        fissure_script = self._install_path / "fissure.py"
        if not fissure_script.exists():
            fissure_script = self._install_path / "FISSURE.py"
        if not fissure_script.exists():
            return {"error": "FISSURE launcher script not found"}

        env = os.environ.copy()
        if context:
            env["RAVEN_FREQ"] = str(context.get("freq_mhz", ""))
            env["RAVEN_IQ_FILE"] = str(context.get("iq_file", ""))

        try:
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/python3", str(fissure_script),
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return {"status": "launched", "pid": proc.pid}
        except Exception as e:
            return {"error": str(e)}

    def get_status(self):
        return {
            "available": self._available,
            "install_path": str(self._install_path),
            "protocol_count": len(self._protocols),
        }
