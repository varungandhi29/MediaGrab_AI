import json
import time
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import defaultdict, deque
from ..config import settings


class FeedbackManager:
    """
    Manages anonymous link failure reports, thumbs up/down user feedback,
    and rolling domain health metrics.
    Strictly preserves privacy: zero IP addresses, zero user identifiers.
    """
    def __init__(self):
        self._lock = asyncio.Lock()
        self.storage_dir = settings.STORAGE_DIR
        self.reports_file = self.storage_dir / "user_reports.json"
        self.feedback_file = self.storage_dir / "user_ratings.json"
        self.domain_history_file = self.storage_dir / "domain_history.json"

        # In-memory rolling window of last 50 attempts per domain for real-time alerting
        # domain -> deque of bool (True=success, False=failure), maxlen 50
        self._domain_attempts: Dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
        self._unsupported_domains_counter: Dict[str, int] = defaultdict(int)
        self._ready_durations: deque = deque(maxlen=100)

        self._load_state()

    def _load_state(self):
        try:
            if self.domain_history_file.exists():
                data = json.loads(self.domain_history_file.read_text(encoding="utf-8"))
                for domain, history in data.get("attempts", {}).items():
                    self._domain_attempts[domain] = deque(history, maxlen=50)
                for domain, count in data.get("unsupported", {}).items():
                    self._unsupported_domains_counter[domain] = count
                for d in data.get("ready_durations", []):
                    self._ready_durations.append(d)
        except Exception:
            pass

    async def _save_state(self):
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "attempts": {d: list(hist) for d, hist in self._domain_attempts.items()},
                "unsupported": dict(self._unsupported_domains_counter),
                "ready_durations": list(self._ready_durations),
                "updated_at": time.time(),
            }
            self.domain_history_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    async def record_attempt(self, domain: str, success: bool, duration_seconds: Optional[float] = None, error_class: Optional[str] = None):
        """
        Records an extraction or playback attempt for rolling domain health.
        """
        clean_domain = domain.lower().strip()
        if not clean_domain:
            return

        async with self._lock:
            self._domain_attempts[clean_domain].append(success)
            if success and duration_seconds is not None and duration_seconds > 0:
                self._ready_durations.append(duration_seconds)
            if not success and error_class in ("unsupported_site", "file_sharing", "unsupported_drm"):
                self._unsupported_domains_counter[clean_domain] += 1
            await self._save_state()

    async def save_report(self, domain: str, error_class: str, job_id: Optional[str] = None, tier_results: Optional[dict] = None, comment: Optional[str] = None) -> Dict[str, Any]:
        """
        Saves an anonymous 1-click link failure report.
        """
        clean_domain = domain.lower().strip()
        record = {
            "timestamp": time.time(),
            "domain": clean_domain,
            "error_class": error_class,
            "job_id": job_id,
            "tier_results": tier_results or {},
            "comment": (comment or "").strip()[:500],
        }

        async with self._lock:
            # Increment unsupported counter if applicable
            self._unsupported_domains_counter[clean_domain] += 1
            reports = []
            if self.reports_file.exists():
                try:
                    reports = json.loads(self.reports_file.read_text(encoding="utf-8"))
                except Exception:
                    reports = []
            reports.append(record)
            # Keep max 500 recent reports
            if len(reports) > 500:
                reports = reports[-500:]
            self.reports_file.write_text(json.dumps(reports, indent=2), encoding="utf-8")

        return {"status": "ok", "message": "Report logged anonymously. Thank you for your feedback!"}

    async def save_rating(self, domain: str, rating: str, job_id: Optional[str] = None, action: str = "play") -> Dict[str, Any]:
        """
        Saves an anonymous thumbs up/down user rating.
        """
        clean_domain = domain.lower().strip()
        record = {
            "timestamp": time.time(),
            "domain": clean_domain,
            "rating": "up" if rating.lower() in ("up", "+1", "thumbs_up") else "down",
            "action": action,
            "job_id": job_id,
        }

        async with self._lock:
            ratings = []
            if self.feedback_file.exists():
                try:
                    ratings = json.loads(self.feedback_file.read_text(encoding="utf-8"))
                except Exception:
                    ratings = []
            ratings.append(record)
            if len(ratings) > 1000:
                ratings = ratings[-1000:]
            self.feedback_file.write_text(json.dumps(ratings, indent=2), encoding="utf-8")

        return {"status": "ok", "message": "Rating saved. Thank you!"}

    async def get_ux_metrics(self) -> Dict[str, Any]:
        """
        Calculates all Section 6 dashboard metrics:
        - success rate per domain
        - top failing domains
        - top error classes
        - average time to ready
        - thumbs up/down ratio
        - alerts when supported site success drops below 85% over last 20 attempts
        - weekly summary of top 10 unsupported domains
        """
        async with self._lock:
            # 1. Success rate per domain over last 20 attempts
            domain_rates = {}
            alerts = []
            failing_counts = defaultdict(int)

            # Major supported sites to monitor for alerts
            supported_to_monitor = {"youtube.com", "vimeo.com", "x.com", "twitter.com", "reddit.com", "twitch.tv", "soundcloud.com"}

            for domain, history in self._domain_attempts.items():
                recent = list(history)[-20:]
                if not recent:
                    continue
                successes = sum(1 for x in recent if x)
                total = len(recent)
                rate = successes / total
                failures = total - successes
                failing_counts[domain] = failures

                domain_rates[domain] = {
                    "total_recent": total,
                    "successes": successes,
                    "failures": failures,
                    "success_rate_percent": round(rate * 100.0, 1),
                }

                # Alert if supported site success rate drops below 85% over last 20 attempts
                is_supported = any(s in domain for s in supported_to_monitor)
                if is_supported and total >= 5 and rate < 0.85:
                    alerts.append({
                        "domain": domain,
                        "current_rate_percent": round(rate * 100.0, 1),
                        "threshold_percent": 85.0,
                        "sample_size": total,
                        "severity": "warning" if rate >= 0.50 else "critical",
                        "message": f"{domain} success rate is {round(rate * 100.0, 1)}% (< 85%) over the last {total} attempts.",
                    })

            # 2. Top failing domains
            top_failing = sorted(
                [{"domain": d, "failures": c} for d, c in failing_counts.items() if c > 0],
                key=lambda x: x["failures"],
                reverse=True
            )[:10]

            # 3. Read reports for top error classes
            reports = []
            if self.reports_file.exists():
                try:
                    reports = json.loads(self.reports_file.read_text(encoding="utf-8"))
                except Exception:
                    reports = []

            error_counts = defaultdict(int)
            for r in reports:
                error_counts[r.get("error_class", "unknown")] += 1

            top_errors = sorted(
                [{"error_class": k, "count": v} for k, v in error_counts.items()],
                key=lambda x: x["count"],
                reverse=True
            )

            # 4. Average time to ready
            avg_time = 0.0
            if self._ready_durations:
                avg_time = round(sum(self._ready_durations) / len(self._ready_durations), 2)

            # 5. Thumbs up/down ratio
            ratings = []
            if self.feedback_file.exists():
                try:
                    ratings = json.loads(self.feedback_file.read_text(encoding="utf-8"))
                except Exception:
                    ratings = []

            thumbs_up = sum(1 for r in ratings if r.get("rating") == "up")
            thumbs_down = sum(1 for r in ratings if r.get("rating") == "down")
            total_ratings = thumbs_up + thumbs_down
            satisfaction_rate = round((thumbs_up / total_ratings * 100.0), 1) if total_ratings > 0 else 100.0

            # 6. Weekly summary of top 10 unsupported domains
            top_unsupported = sorted(
                [{"domain": d, "request_count": c} for d, c in self._unsupported_domains_counter.items() if c > 0],
                key=lambda x: x["request_count"],
                reverse=True
            )[:10]

            return {
                "domain_success_rates": domain_rates,
                "alerts": alerts,
                "top_failing_domains": top_failing,
                "top_error_classes": top_errors,
                "average_time_to_ready_seconds": avg_time,
                "feedback": {
                    "thumbs_up": thumbs_up,
                    "thumbs_down": thumbs_down,
                    "total": total_ratings,
                    "satisfaction_rate_percent": satisfaction_rate,
                },
                "top_unsupported_domains_weekly": top_unsupported,
            }


feedback_manager = FeedbackManager()
