import time
import asyncio
from collections import defaultdict, deque
from typing import Dict, Any, List, Optional
from .error_classifier import FailureCategory


class MetricsCollector:
    """
    Thread-safe telemetry collector for extraction pipeline resilience.
    Computes platform success rates, error classification breakdown, and domain trends.
    """
    def __init__(self, max_recent_events: int = 500):
        self.max_recent_events = max_recent_events
        self._lock = asyncio.Lock()

        # Rolling history of events: (timestamp, platform, domain, tier, success, category)
        self.recent_events: deque = deque(maxlen=max_recent_events)

        # Cumulative counters
        self.total_requests: int = 0
        self.total_successes: int = 0
        self.total_failures: int = 0

        # Category counters
        self.failure_categories: Dict[str, int] = defaultdict(int)

        # Tier counters
        self.tier_attempts: Dict[str, int] = defaultdict(int)
        self.tier_successes: Dict[str, int] = defaultdict(int)

        # Domain stats: {domain: {"attempts": int, "successes": int, "failures": int, "last_error": str, "last_error_time": float, "categories": {cat: count}}}
        self.domain_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "last_error": None,
            "last_error_time": None,
            "categories": defaultdict(int)
        })

    async def record_attempt(
        self,
        platform: str,
        domain: str,
        tier: str,
        success: bool,
        category: Optional[FailureCategory] = None,
        error_msg: Optional[str] = None
    ):
        now = time.time()
        cat_str = category.value if category else ("SUCCESS" if success else "UNKNOWN")

        async with self._lock:
            self.total_requests += 1
            if success:
                self.total_successes += 1
            else:
                self.total_failures += 1
                self.failure_categories[cat_str] += 1

            self.tier_attempts[tier] += 1
            if success:
                self.tier_successes[tier] += 1

            d_entry = self.domain_stats[domain]
            d_entry["attempts"] += 1
            if success:
                d_entry["successes"] += 1
            else:
                d_entry["failures"] += 1
                d_entry["last_error"] = error_msg[:200] if error_msg else cat_str
                d_entry["last_error_time"] = now
                d_entry["categories"][cat_str] += 1

            self.recent_events.append({
                "timestamp": now,
                "platform": platform,
                "domain": domain,
                "tier": tier,
                "success": success,
                "category": cat_str,
            })

    async def get_metrics_summary(self) -> Dict[str, Any]:
        async with self._lock:
            now = time.time()
            cutoff_1h = now - 3600
            cutoff_24h = now - 86400

            # Calculate rolling 1h and 24h success rates
            events_1h = [e for e in self.recent_events if e["timestamp"] >= cutoff_1h]
            events_24h = [e for e in self.recent_events if e["timestamp"] >= cutoff_24h]

            rate_1h = (sum(1 for e in events_1h if e["success"]) / len(events_1h) * 100) if events_1h else 100.0
            rate_24h = (sum(1 for e in events_24h if e["success"]) / len(events_24h) * 100) if events_24h else 100.0
            rate_all = (self.total_successes / self.total_requests * 100) if self.total_requests > 0 else 100.0

            # Group success rate by platform
            platform_groups: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "success": 0})
            for e in self.recent_events:
                p = e["platform"] or "Other"
                platform_groups[p]["total"] += 1
                if e["success"]:
                    platform_groups[p]["success"] += 1

            platform_success_rates = []
            for plat, data in platform_groups.items():
                pct = round((data["success"] / data["total"] * 100.0), 1) if data["total"] > 0 else 100.0
                platform_success_rates.append({
                    "platform": plat,
                    "total_attempts": data["total"],
                    "success_count": data["success"],
                    "success_rate_percent": pct,
                })
            platform_success_rates.sort(key=lambda x: x["total_attempts"], reverse=True)

            # Failure category distribution
            failure_dist = {
                cat: count for cat, count in self.failure_categories.items()
            }

            # Tier effectiveness breakdown
            tier_metrics = []
            for t, attempts in self.tier_attempts.items():
                succ = self.tier_successes.get(t, 0)
                rate = round((succ / attempts * 100.0), 1) if attempts > 0 else 0.0
                tier_metrics.append({
                    "tier": t,
                    "attempts": attempts,
                    "successes": succ,
                    "success_rate_percent": rate,
                })

            # Domain breakdown (top active domains)
            domain_summary = []
            for d, d_stat in list(self.domain_stats.items())[:20]:
                attempts = d_stat["attempts"]
                succ = d_stat["successes"]
                rate = round((succ / attempts * 100.0), 1) if attempts > 0 else 100.0
                dominant_cat = (
                    max(d_stat["categories"], key=d_stat["categories"].get)
                    if d_stat["categories"] else "NONE"
                )
                domain_summary.append({
                    "domain": d,
                    "attempts": attempts,
                    "success_rate_percent": rate,
                    "last_error": d_stat["last_error"],
                    "last_error_time": d_stat["last_error_time"],
                    "dominant_failure_category": dominant_cat,
                })
            domain_summary.sort(key=lambda x: x["attempts"], reverse=True)

            return {
                "overall_success_rate_percent": round(rate_all, 1),
                "rolling_1h_success_rate_percent": round(rate_1h, 1),
                "rolling_24h_success_rate_percent": round(rate_24h, 1),
                "total_requests": self.total_requests,
                "total_successes": self.total_successes,
                "total_failures": self.total_failures,
                "platforms": platform_success_rates,
                "failure_categories": failure_dist,
                "tiers": tier_metrics,
                "top_domains": domain_summary,
            }


metrics_collector = MetricsCollector()
