import sys
import time
import asyncio
import logging
import subprocess
from typing import Dict, Any, Optional, List
import httpx
import yt_dlp

from ..config import settings
from .alert_manager import alert_manager
from .error_classifier import FailureCategory

logger = logging.getLogger("mediagrab.self_heal")


class YtDlpSelfHealer:
    """
    Self-Healing Dependency Manager for yt-dlp:
    1. Checks PyPI for the latest release on schedule or on demand.
    2. Performs atomic upgrade in an isolated subprocess.
    3. Runs an automated smoke-test suite before declaring healthy.
    4. Automatically rolls back to the last known-good version if smoke test fails.
    """
    def __init__(self):
        self.last_check_time: Optional[float] = None
        self.last_known_good_version: str = getattr(yt_dlp.version, "__version__", "unknown")
        self.current_version: str = getattr(yt_dlp.version, "__version__", "unknown")
        self.latest_pypi_version: Optional[str] = None
        self.last_status: str = "idle"  # idle, checking, updating, healthy, rolled_back, failed
        self.last_error: Optional[str] = None
        self.smoke_test_results: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()

    def get_installed_version(self) -> str:
        try:
            res = subprocess.run(
                [sys.executable, "-m", "yt_dlp", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return getattr(yt_dlp.version, "__version__", "unknown")

    async def check_for_updates(self) -> Optional[str]:
        """Queries PyPI JSON API for the latest yt-dlp release version."""
        url = "https://pypi.org/pypi/yt-dlp/json"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    latest = data.get("info", {}).get("version")
                    self.latest_pypi_version = latest
                    return latest
        except Exception as e:
            logger.warning(f"Failed to check PyPI for yt-dlp update: {e}")
        return None

    async def run_smoke_tests(self, timeout_per_test: int = 10) -> bool:
        """
        Runs validation smoke tests on the newly installed yt-dlp executable.
        Verifies CLI responsiveness, JSON extraction capability, and Python import integrity.
        """
        self.smoke_test_results = []
        all_passed = True

        # Test 1: CLI Version Query
        t1_start = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "yt_dlp", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_per_test)
            t1_success = proc.returncode == 0 and bool(stdout.strip())
            self.smoke_test_results.append({
                "test": "CLI Executable Version Check",
                "success": t1_success,
                "output": stdout.decode("utf-8", errors="replace").strip(),
                "duration_seconds": round(time.time() - t1_start, 2),
            })
            if not t1_success:
                all_passed = False
        except Exception as e:
            self.smoke_test_results.append({
                "test": "CLI Executable Version Check",
                "success": False,
                "output": str(e),
                "duration_seconds": round(time.time() - t1_start, 2),
            })
            all_passed = False

        # Test 2: Extraction Engine Self-Test on Sample Direct Source
        t2_start = time.time()
        try:
            # Test yt-dlp on a public test media stream
            sample_test_url = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4"
            proc2 = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "yt_dlp",
                "--dump-json",
                "--no-download",
                "--no-check-certificates",
                sample_test_url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout2, stderr2 = await asyncio.wait_for(proc2.communicate(), timeout=timeout_per_test)
            t2_success = proc2.returncode == 0 and b'"id":' in stdout2
            self.smoke_test_results.append({
                "test": "Direct Stream JSON Metadata Extraction",
                "success": t2_success,
                "output": "JSON extracted successfully" if t2_success else stderr2.decode("utf-8", errors="replace")[:120],
                "duration_seconds": round(time.time() - t2_start, 2),
            })
            if not t2_success:
                all_passed = False
        except Exception as e:
            self.smoke_test_results.append({
                "test": "Direct Stream JSON Metadata Extraction",
                "success": False,
                "output": str(e),
                "duration_seconds": round(time.time() - t2_start, 2),
            })
            all_passed = False

        # Test 3: Python Library Interface Integrity
        t3_start = time.time()
        try:
            proc3 = await asyncio.create_subprocess_exec(
                sys.executable, "-c", "import yt_dlp; ydl = yt_dlp.YoutubeDL({'quiet': True}); print('OK')",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout3, stderr3 = await asyncio.wait_for(proc3.communicate(), timeout=timeout_per_test)
            t3_success = proc3.returncode == 0 and b"OK" in stdout3
            self.smoke_test_results.append({
                "test": "Python Library Binding & Instantiation",
                "success": t3_success,
                "output": "OK" if t3_success else stderr3.decode("utf-8", errors="replace")[:120],
                "duration_seconds": round(time.time() - t3_start, 2),
            })
            if not t3_success:
                all_passed = False
        except Exception as e:
            self.smoke_test_results.append({
                "test": "Python Library Binding & Instantiation",
                "success": False,
                "output": str(e),
                "duration_seconds": round(time.time() - t3_start, 2),
            })
            all_passed = False

        return all_passed

    async def update_and_verify(self, force: bool = False) -> Dict[str, Any]:
        """
        Executes safe upgrade flow:
        Checks version -> upgrades -> runs smoke tests -> rolls back if broken.
        """
        async with self._lock:
            self.last_check_time = time.time()
            self.current_version = self.get_installed_version()
            self.last_status = "checking"

            latest = await self.check_for_updates()
            if not latest and not force:
                self.last_status = "healthy"
                return {
                    "status": "healthy",
                    "installed_version": self.current_version,
                    "latest_version": self.latest_pypi_version,
                    "message": "Already up to date or update check unavailable.",
                }

            if latest == self.current_version and not force:
                self.last_status = "healthy"
                return {
                    "status": "healthy",
                    "installed_version": self.current_version,
                    "latest_version": latest,
                    "message": f"yt-dlp is current (v{self.current_version}).",
                }

            logger.info(f"Self-healer: Upgrading yt-dlp from v{self.current_version} to v{latest or 'latest'}...")
            self.last_status = "updating"
            self.last_known_good_version = self.current_version

            # Attempt upgrade via pip in subprocess
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
                if proc.returncode != 0:
                    err = stderr.decode("utf-8", errors="replace")[:200]
                    self.last_status = "failed"
                    self.last_error = f"pip install failed: {err}"
                    return {
                        "status": "failed",
                        "error": self.last_error,
                        "installed_version": self.current_version
                    }
            except Exception as e:
                self.last_status = "failed"
                self.last_error = str(e)
                return {
                    "status": "failed",
                    "error": str(e),
                    "installed_version": self.current_version
                }

            # Run smoke tests on upgraded build
            logger.info("Self-healer: Running post-update smoke test suite...")
            tests_passed = await self.run_smoke_tests()

            if tests_passed:
                new_ver = self.get_installed_version()
                self.current_version = new_ver
                self.last_known_good_version = new_ver
                self.last_status = "healthy"
                logger.info(f"Self-healer: yt-dlp successfully updated to v{new_ver} and verified with smoke tests.")
                return {
                    "status": "updated",
                    "previous_version": self.last_known_good_version,
                    "current_version": new_ver,
                    "smoke_tests": self.smoke_test_results,
                    "message": f"yt-dlp successfully updated to v{new_ver}.",
                }

            # Smoke tests failed: Trigger Automatic Rollback!
            logger.error("Self-healer: Smoke tests failed after update! Rolling back to last known good version...")
            self.last_status = "rolling_back"

            rollback_proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", f"yt-dlp=={self.last_known_good_version}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await asyncio.wait_for(rollback_proc.communicate(), timeout=90)
            rolled_back_version = self.get_installed_version()
            self.current_version = rolled_back_version
            self.last_status = "rolled_back"
            self.last_error = "Smoke test failed post-update. Rolled back to prevent production outage."

            # Trigger resilience alert
            await alert_manager.evaluate_and_alert_if_needed(
                domain="yt-dlp-dependency",
                failure_category=FailureCategory.EXTRACTOR_OUTDATED,
                sample_error=f"Update to v{latest} failed smoke tests. Automatically rolled back to v{rolled_back_version}.",
                tiers_attempted=["ytdlp_smoke_tests"],
                circuit_open=True,
            )

            return {
                "status": "rolled_back",
                "installed_version": rolled_back_version,
                "target_version": latest,
                "smoke_tests": self.smoke_test_results,
                "message": f"Update failed smoke test. Automatically rolled back to v{rolled_back_version}.",
            }

    def get_status(self) -> Dict[str, Any]:
        return {
            "current_version": self.current_version,
            "last_known_good_version": self.last_known_good_version,
            "latest_pypi_version": self.latest_pypi_version,
            "status": self.last_status,
            "last_check_time": self.last_check_time,
            "last_error": self.last_error,
            "smoke_tests": self.smoke_test_results,
        }


ytdlp_self_healer = YtDlpSelfHealer()


async def start_self_healing_scheduler():
    """Background task running scheduled yt-dlp update checks every 24 hours."""
    interval_seconds = settings.YTDLP_UPDATE_CHECK_INTERVAL_HOURS * 3600
    # Wait 60s after server startup before first check
    await asyncio.sleep(60)

    while True:
        try:
            if settings.YTDLP_AUTO_UPDATE_ENABLED:
                logger.info("Running scheduled yt-dlp self-healing dependency check...")
                await ytdlp_self_healer.update_and_verify(force=False)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in self-healing background scheduler: {e}")

        await asyncio.sleep(interval_seconds)
