import pytest
from app.services.ai_assistant import detect_platform_from_url, ai_assistant


def test_detect_platform():
    yt = detect_platform_from_url("https://www.youtube.com/watch?v=12345")
    assert yt["platform"] == "YouTube"

    tt = detect_platform_from_url("https://www.tiktok.com/@user/video/12345")
    assert tt["platform"] == "TikTok"

    tw = detect_platform_from_url("https://x.com/status/12345")
    assert "Twitter" in tw["platform"] or "X" in tw["platform"]

    direct = detect_platform_from_url("https://example.com/assets/sample.mp4")
    assert "Direct Video" in direct["platform"]


@pytest.mark.asyncio
async def test_ai_recommendation_use_cases():
    qualities = ["2160p (4K)", "1080p (Full HD)", "720p (HD)", "480p (SD)", "Audio only (MP3)"]

    # Mobile use case
    rec_mobile = await ai_assistant.get_recommendation(
        url="https://youtube.com/watch?v=abc",
        use_case="mobile",
        available_qualities=qualities
    )
    assert "480p" in rec_mobile.recommended_quality or "720p" in rec_mobile.recommended_quality

    # Podcast use case
    rec_podcast = await ai_assistant.get_recommendation(
        url="https://youtube.com/watch?v=abc",
        use_case="podcast",
        available_qualities=qualities
    )
    assert "Audio" in rec_podcast.recommended_quality or "MP3" in rec_podcast.recommended_quality

    # Archive / editing use case
    rec_archive = await ai_assistant.get_recommendation(
        url="https://youtube.com/watch?v=abc",
        use_case="archive",
        available_qualities=qualities
    )
    assert "2160p" in rec_archive.recommended_quality or "1080p" in rec_archive.recommended_quality


@pytest.mark.asyncio
async def test_ai_error_explanation():
    exp = await ai_assistant.explain_error(
        url="http://127.0.0.1",
        raw_error="SSRF violation: Hostname resolves to restricted internal IP"
    )
    assert "SSRF" in exp.human_summary or "Security" in exp.category
