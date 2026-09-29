import time
import asyncio
import logging
from typing import Dict, Any, List, Optional
import httpx

from ..config import settings
from .error_classifier import FailureCategory

logger = logging.getLogger("mediagrab.alert")


class AlertManager:
    """
    Automated monitoring and anomaly alert dispatcher.
    Detects persistent failure spikes per domain where automated retries/circuits
    cannot recover, and notifies operators via webhook (Slack/Discord/generic).
    """
    def __init__(self, throttle_cooldown_seconds: int = 1800):  # 30 mins between duplicate alerts
        self.throttle_cooldown = throttle_cooldown_seconds
        self.alerts_history: List[Dict[str, Any]] = []
        self._last_alerted_by_domain: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def evaluate_and_alert_if_needed(
        self,
        domain: str,
        failure_category: FailureCategory,
        sample_error: str,
        tiers_attempted: List[str],
        circuit_open: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates whether a domain failure pattern represents a structural breakdown
        warranting an operator alert.
        """
        # Only alert for structural issues (EXTRACTOR_OUTDATED, persistent BOT_PROTECTION, or Circuit OPEN)
        is_actionable = (
            failure_category == FailureCategory.EXTRACTOR_OUTDATED or
            circuit_open or
            (failure_category == FailureCategory.BOT_PROTECTION and "headless_browser" in tiers_attempted)
        )

        if not is_actionable:
            return None

        now = time.time()
        async with self._lock:
            # Check throttling: avoid alert storms
            last_alert_time = self._last_alerted_by_domain.get(domain, 0.0)
            if (now - last_alert_time) < self.throttle_cooldown:
                logger.debug(f"Alert throttled for {domain} (last sent {now - last_alert_time:.0f}s ago)")
                return None

            self._last_alerted_by_domain[domain] = now

            alert_record = {
                "id": f"alert_{int(now)}_{domain}",
                "timestamp": now,
                "domain": domain,
                "category": failure_category.value,
                "sample_error": sample_error[:300],
                "tiers_attempted": tiers_attempted,
                "circuit_tripped": circuit_open,
                "severity": "HIGH" if circuit_open else "MEDIUM",
                "recommended_action": self._determine_recommended_action(failure_category, domain),
                "webhook_status": "pending",
            }

            self.alerts_history.insert(0, alert_record)
            if len(self.alerts_history) > 100:
                self.alerts_history = self.alerts_history[:100]

        # Dispatch webhook in background
        asyncio.create_task(self._dispatch_webhook(alert_record))
        return alert_record

    def _determine_recommended_action(self, category: FailureCategory, domain: str) -> str:
        if category == FailureCategory.EXTRACTOR_OUTDATED:
            return (
                f"Site layout for '{domain}' likely changed. Trigger yt-dlp auto-update "
                "or review extractor parser rules."
            )
        elif category == FailureCategory.BOT_PROTECTION:
            return (
                f"Source '{domain}' deployed an advanced anti-bot challenge blocking both "
                "yt-dlp and headless Chromium. Requires investigation of token headers."
            )
        else:
            return f"Persistent failure rate spike detected on domain '{domain}'. Manual investigation recommended."

    async def _dispatch_webhook(self, alert: Dict[str, Any]):
        webhook_url = settings.ALERT_WEBHOOK_URL
        if not webhook_url:
            alert["webhook_status"] = "skipped (no webhook URL configured)"
            return

        payload = {
            "text": f"🚨 *MediaGrab AI Resilience Alert*: Extraction Failure Spike on `{alert['domain']}`",
            "attachments": [
                {
                    "color": "#ef4444" if alert["severity"] == "HIGH" else "#f59e0b",
                    "fields": [
                        {"title": "Domain", "value": alert["domain"], "short": True},
                        {"title": "Category", "value": alert["category"], "short": True},
                        {"title": "Severity", "value": alert["severity"], "short": True},
                        {"title": "Circuit Breaker", "value": "OPEN (Tripped)" if alert["circuit_tripped"] else "Active", "short": True},
                        {"title": "Tiers Attempted", "value": ", ".join(alert["tiers_attempted"]), "short": False},
                        {"title": "Sample Error", "value": f"```{alert['sample_error']}```", "short": False},
                        {"title": "Recommended Action", "value": alert["recommended_action"], "short": False},
                    ],
                    "footer": "MediaGrab AI Self-Healing System",
                    "ts": int(alert["timestamp"]),
                }
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(webhook_url, json=payload)
                if resp.status_code in (200, 204):
                    alert["webhook_status"] = "delivered"
                    logger.info(f"Webhook alert successfully dispatched for {alert['domain']}")
                else:
                    alert["webhook_status"] = f"failed (HTTP {resp.status_code})"
                    logger.warning(f"Webhook alert dispatch failed with status {resp.status_code}")
        except Exception as e:
            alert["webhook_status"] = f"error: {str(e)[:100]}"
            logger.error(f"Error dispatching webhook alert: {e}")

    async def get_alerts_history(self) -> List[Dict[str, Any]]:
        async with self._lock:
            return list(self.alerts_history)


alert_manager = AlertManager()
