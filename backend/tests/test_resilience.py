import pytest
import time
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.resilience import (
    FailureCategory,
    RecoveryAction,
    classify_error,
    extract_domain_from_url,
    CircuitState,
    circuit_breaker_registry,
    metrics_collector,
    alert_manager,
    ytdlp_self_healer,
    worker_supervisor,
)


def test_error_classification_transient():
    cls = classify_error("HTTP Error 429: Too Many Requests", "https://youtube.com/watch?v=123", tier="ytdlp")
    assert cls.category == FailureCategory.TRANSIENT
    assert cls.action == RecoveryAction.RETRY_BACKOFF
    assert cls.can_retry is True

    cls_conn = classify_error("Connection reset by peer", "https://vimeo.com/456", tier="direct")
    assert cls_conn.category == FailureCategory.TRANSIENT
    assert cls_conn.can_retry is True


def test_error_classification_source_unavailable():
    cls_priv = classify_error("This video is private or requires login", "https://youtube.com/watch?v=123", tier="ytdlp")
    assert cls_priv.category == FailureCategory.SOURCE_UNAVAILABLE
    assert cls_priv.action == RecoveryAction.FAIL_IMMEDIATELY
    assert cls_priv.can_retry is False
    assert "private" in cls_priv.user_message.lower()

    cls_geo = classify_error("Video not available in your country (geo-restricted)", "https://youtube.com/watch?v=123", tier="ytdlp")
    assert cls_geo.category == FailureCategory.SOURCE_UNAVAILABLE
    assert cls_geo.action == RecoveryAction.FAIL_IMMEDIATELY
    assert "geo-restricted" in cls_geo.user_message.lower()


def test_error_classification_extractor_outdated():
    cls = classify_error("Unable to extract video data; Regex pattern not found", "https://instagram.com/p/123", tier="ytdlp")
    assert cls.category == FailureCategory.EXTRACTOR_OUTDATED
    assert cls.action == RecoveryAction.FALL_THROUGH_TIER
    assert cls.needs_dependency_alert is True
    assert cls.can_retry is False


def test_error_classification_bot_protection():
    cls = classify_error("Cloudflare challenge: Just a moment... verify you are human", "https://tiktok.com/@user/video/123", tier="ytdlp")
    assert cls.category == FailureCategory.BOT_PROTECTION
    assert cls.action == RecoveryAction.FALL_THROUGH_TIER
    assert cls.can_retry is False


def test_error_classification_resource_exhausted():
    cls = classify_error("No space left on device: Disk full", "https://example.com/video.mp4", tier="direct")
    assert cls.category == FailureCategory.RESOURCE_EXHAUSTED
    assert cls.action == RecoveryAction.QUEUE_WAIT
    assert cls.can_retry is True


@pytest.mark.asyncio
async def test_circuit_breaker_transitions():
    tier = "test_tier"
    domain = "failing-site.com"

    # Reset any previous state
    await circuit_breaker_registry.reset_circuit(tier, domain)

    # 1. Initially CLOSED
    assert await circuit_breaker_registry.can_execute(tier, domain) is True

    # 2. Record 5 failures out of 5 (100% failure rate > 80% threshold with min 5 samples)
    for _ in range(5):
        await circuit_breaker_registry.record_result(tier, domain, success=False, category=FailureCategory.TRANSIENT)

    # Circuit should now be OPEN
    status = await circuit_breaker_registry.get_circuit_status(tier, domain)
    assert status["state"] == CircuitState.OPEN.value
    assert status["failure_rate"] == 1.0
    assert status["trip_count"] == 1

    # While OPEN and within cooldown, can_execute returns False
    assert await circuit_breaker_registry.can_execute(tier, domain) is False

    # Simulate cooldown expiry by adjusting last_tripped_at
    entry = circuit_breaker_registry._get_or_create(tier, domain)
    entry.last_tripped_at = time.time() - 2000  # past 1800s cooldown

    # Next call transitions to HALF_OPEN to allow trial
    can_trial = await circuit_breaker_registry.can_execute(tier, domain)
    assert can_trial is True
    assert entry.state == CircuitState.HALF_OPEN

    # Record success on trial request -> circuit resets to CLOSED
    await circuit_breaker_registry.record_result(tier, domain, success=True)
    assert entry.state == CircuitState.CLOSED
    assert await circuit_breaker_registry.can_execute(tier, domain) is True

    # Clean up
    await circuit_breaker_registry.reset_circuit(tier, domain)


@pytest.mark.asyncio
async def test_metrics_and_telemetry_collection():
    await metrics_collector.record_attempt("YouTube", "youtube.com", "ytdlp", success=True)
    await metrics_collector.record_attempt("YouTube", "youtube.com", "ytdlp", success=False, category=FailureCategory.TRANSIENT, error_msg="Timeout")

    summary = await metrics_collector.get_metrics_summary()
    assert summary["total_requests"] >= 2
    assert "platforms" in summary
    assert "failure_categories" in summary
    assert "TRANSIENT" in summary["failure_categories"]


@pytest.mark.asyncio
async def test_alert_manager_evaluation():
    alert = await alert_manager.evaluate_and_alert_if_needed(
        domain="broken-structure-site.com",
        failure_category=FailureCategory.EXTRACTOR_OUTDATED,
        sample_error="Signature extraction failed: regex pattern mismatch",
        tiers_attempted=["ytdlp"],
        circuit_open=True,
    )
    assert alert is not None
    assert alert["domain"] == "broken-structure-site.com"
    assert alert["category"] == "EXTRACTOR_OUTDATED"
    assert alert["severity"] == "HIGH"

    # Throttling check: Immediate second alert for same domain should be throttled
    second_alert = await alert_manager.evaluate_and_alert_if_needed(
        domain="broken-structure-site.com",
        failure_category=FailureCategory.EXTRACTOR_OUTDATED,
        sample_error="Another error",
        tiers_attempted=["ytdlp"],
        circuit_open=True,
    )
    assert second_alert is None


@pytest.mark.asyncio
async def test_resilience_api_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # GET /api/system/resilience
        resp = await client.get("/api/system/resilience")
        assert resp.status_code == 200
        data = resp.json()
        assert "metrics" in data
        assert "circuits" in data
        assert "ytdlp" in data
        assert "workers" in data
        assert "recent_alerts" in data

        # POST /api/system/resilience/circuits/reset
        resp_reset = await client.post("/api/system/resilience/circuits/reset", json={})
        assert resp_reset.status_code == 200
        assert "success" in resp_reset.json()["status"]

        # POST /api/system/resilience/test-alert
        resp_alert = await client.post("/api/system/resilience/test-alert?domain=test-domain.org")
        assert resp_alert.status_code == 200
