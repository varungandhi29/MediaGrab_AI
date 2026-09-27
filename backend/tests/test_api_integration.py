import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_health_and_stats_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Test /api/health
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "app" in data

        # Test /api/stats
        resp_stats = await client.get("/api/stats")
        assert resp_stats.status_code == 200
        stats = resp_stats.json()
        assert stats["ssrf_protection_active"] is True
        assert "sliding_window_rate_limits" in stats


@pytest.mark.asyncio
async def test_metadata_endpoint_ssrf_rejection():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Attempt to target internal IP / cloud metadata
        resp = await client.post("/api/metadata", json={"url": "http://169.254.169.254/latest/meta-data"})
        assert resp.status_code == 400
        err = resp.json()["detail"]
        assert "Security Alert" in err or "blocked" in err.lower() or "restricted" in err.lower()

        # Attempt to target localhost
        resp_local = await client.post("/api/metadata", json={"url": "http://localhost:8000/api/health"})
        assert resp_local.status_code == 400

        # Attempt to target file:// URI scheme
        resp_file = await client.post("/api/metadata", json={"url": "file:///etc/passwd"})
        assert resp_file.status_code == 400


@pytest.mark.asyncio
async def test_ai_detect_and_recommend():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Detect platform
        resp = await client.post("/api/ai/detect", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
        assert resp.status_code == 200
        assert resp.json()["platform"] == "YouTube"

        # Recommend format
        resp_rec = await client.post(
            "/api/ai/recommend",
            json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "use_case": "podcast",
                "available_qualities": ["1080p", "720p", "Audio only (MP3)"]
            }
        )
        assert resp_rec.status_code == 200
        assert "Audio" in resp_rec.json()["recommended_quality"] or "MP3" in resp_rec.json()["recommended_quality"]
