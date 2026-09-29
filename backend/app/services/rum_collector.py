import time
import asyncio
from typing import Dict, Any, List, Optional
from collections import deque
import logging

from ..resilience.alert_manager import alert_manager

logger = logging.getLogger("mediagrab.rum")


class PlaybackRUMCollector:
    """
    Collects Real User Monitoring (RUM) telemetry for in-browser video playback.
    Tracks Time-to-First-Frame (TTFF), buffering stalls, fallback strategies, and error rate spikes.
    Anonymized: contains strictly zero PII.
    """
    def __init__(self, max_history: int = 500):
        self.max_history = max_history
        self._sessions = deque(maxlen=max_history)
        self._domain_buffering: Dict[str, List[int]] = {}
        self._lock = asyncio.Lock()
        self._last_alert_time: Dict[str, float] = {}

    async def record_session(self, telemetry: Dict[str, Any]) -> None:
        """Records an anonymized playback session."""
        now = time.time()
        record = {
            "timestamp": now,
            "session_id": telemetry.get("session_id", "anon"),
            "browser": telemetry.get("browser", "Other"),
            "os": telemetry.get("os", "Other"),
            "is_mobile": bool(telemetry.get("is_mobile", False)),
            "strategy": telemetry.get("strategy", "native"),
            "ttff_ms": max(0, int(telemetry.get("ttff_ms", 0))),
            "buffering_count": max(0, int(telemetry.get("buffering_count", 0))),
            "buffering_duration_ms": max(0, int(telemetry.get("buffering_duration_ms", 0))),
            "quality_switches": max(0, int(telemetry.get("quality_switches", 0))),
            "success": bool(telemetry.get("success", True)),
            "error_type": telemetry.get("error_type"),
            "error_message": telemetry.get("error_message"),
            "source_domain": telemetry.get("source_domain", "unknown"),
        }

        async with self._lock:
            self._sessions.append(record)
            domain = record["source_domain"]
            if domain and domain != "unknown":
                if domain not in self._domain_buffering:
                    self._domain_buffering[domain] = []
                self._domain_buffering[domain].append(record["buffering_count"])
                if len(self._domain_buffering[domain]) > 50:
                    self._domain_buffering[domain] = self._domain_buffering[domain][-50:]

        # Check for browser-specific error spikes
        await self._check_error_spikes(record["browser"], record["source_domain"])

    async def _check_error_spikes(self, browser: str, domain: str) -> None:
        """Alerts if playback error rate spikes for a given browser or domain."""
        now = time.time()
        key = f"{browser}_{domain}"
        if key in self._last_alert_time and (now - self._last_alert_time[key]) < 1800:
            return  # 30-min throttle

        async with self._lock:
            recent = [s for s in self._sessions if s["browser"] == browser and (now - s["timestamp"]) < 1800]
            if len(recent) < 5:
                return

            failures = [s for s in recent if not s["success"]]
            failure_rate = len(failures) / len(recent)

            if failure_rate >= 0.40:  # >40% playback failure on a specific browser
                self._last_alert_time[key] = now
                err_samples = [f["error_message"] for f in failures if f.get("error_message")]
                sample_err = err_samples[0] if err_samples else "Repeated playback failures"

                await alert_manager.dispatch_alert(
                    domain=domain,
                    category="PLAYBACK_ERROR_SPIKE",
                    error_msg=f"High playback failure rate ({int(failure_rate*100)}%) detected on {browser}. Recent error: {sample_err}",
                    tiers_attempted=["playback_player"],
                    circuit_tripped=False,
                    severity="HIGH",
                    recommended_action=f"Inspect player compatibility or codecs on {browser}. Transcoded MP4 fallback may be required.",
                )

    async def get_summary(self) -> Dict[str, Any]:
        """Calculates aggregated RUM playback metrics for the operations dashboard."""
        now = time.time()
        async with self._lock:
            recent = [s for s in self._sessions if (now - s["timestamp"]) < 86400]  # last 24h

        total_sessions = len(recent)
        if total_sessions == 0:
            return {
                "total_sessions": 0,
                "overall_success_rate": 100.0,
                "avg_ttff_ms": 0,
                "avg_buffering_count": 0.0,
                "browser_breakdown": {},
                "strategy_breakdown": {},
                "high_buffering_domains": [],
            }

        success_count = sum(1 for s in recent if s["success"])
        overall_success_rate = round((success_count / total_sessions) * 100, 1)

        # Average Time-to-First-Frame (TTFF) for successful sessions with positive TTFF
        ttff_values = [s["ttff_ms"] for s in recent if s["success"] and s["ttff_ms"] > 0]
        avg_ttff = round(sum(ttff_values) / len(ttff_values)) if ttff_values else 0

        # Average buffering count
        total_buffering = sum(s["buffering_count"] for s in recent)
        avg_buffering = round(total_buffering / total_sessions, 2)

        # Browser breakdown
        browser_stats = {}
        for s in recent:
            b = s["browser"]
            if b not in browser_stats:
                browser_stats[b] = {"total": 0, "success": 0}
            browser_stats[b]["total"] += 1
            if s["success"]:
                browser_stats[b]["success"] += 1

        browser_breakdown = {}
        for b, st in browser_stats.items():
            browser_breakdown[b] = {
                "total": st["total"],
                "success_rate": round((st["success"] / st["total"]) * 100, 1) if st["total"] > 0 else 100.0,
            }

        # Strategy breakdown
        strategy_stats = {}
        for s in recent:
            strat = s["strategy"]
            strategy_stats[strat] = strategy_stats.get(strat, 0) + 1

        # High buffering domains
        high_buffering = []
        for dom, buff_counts in self._domain_buffering.items():
            if len(buff_counts) >= 3:
                avg_b = sum(buff_counts) / len(buff_counts)
                if avg_b >= 2.0:
                    high_buffering.append({
                        "domain": dom,
                        "avg_stalls_per_play": round(avg_b, 1),
                        "sample_count": len(buff_counts),
                        "recommendation": "Source CDN slow or bitrate excessive. Consider lower default quality.",
                    })

        high_buffering.sort(key=lambda x: x["avg_stalls_per_play"], reverse=True)

        return {
            "total_sessions": total_sessions,
            "overall_success_rate": overall_success_rate,
            "avg_ttff_ms": avg_ttff,
            "avg_buffering_count": avg_buffering,
            "browser_breakdown": browser_breakdown,
            "strategy_breakdown": strategy_stats,
            "high_buffering_domains": high_buffering[:5],
        }


rum_collector = PlaybackRUMCollector()
