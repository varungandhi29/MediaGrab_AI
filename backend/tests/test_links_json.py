import json
import time
import pytest
from pathlib import Path
from app.services.link_checker import check_link_instant
from app.resilience.error_classifier import get_ux_error_details


def load_test_links():
    links_file = Path(__file__).resolve().parent.parent.parent / "tests" / "links.json"
    if not links_file.exists():
        pytest.fail(f"tests/links.json not found at {links_file}")
    return json.loads(links_file.read_text(encoding="utf-8"))


@pytest.mark.parametrize("item", load_test_links(), ids=lambda x: x["id"])
def test_links_json_evaluation(item):
    """
    Evaluates each link in tests/links.json.
    Verifies that:
    1. Supported links are marked as supported/direct media.
    2. Unsupported links are identified in under 5 seconds with clear explanations and next steps.
    3. Prints PASS/FAIL per link with the reason.
    """
    url = item["url"]
    expected = item["expected_category"]
    name = item["name"]

    start_time = time.time()
    result = check_link_instant(url)
    elapsed = time.time() - start_time

    assert elapsed < 5.0, f"Check took {elapsed:.2f}s, expected < 5s for {name}"

    try:
        if expected == "supported":
            assert result.status == "supported_site", f"Expected supported_site, got {result.status}"
            assert result.can_extract is True
            print(f"\n[PASS] {name}: Classified as '{result.label}' in {elapsed*1000:.1f}ms")

        elif expected == "direct_media":
            assert result.status == "direct_media", f"Expected direct_media, got {result.status}"
            assert result.can_extract is True
            print(f"\n[PASS] {name}: Classified as '{result.label}' in {elapsed*1000:.1f}ms")

        elif expected == "unsupported_file_sharing":
            assert result.status == "unsupported_file_sharing"
            assert result.can_extract is False
            assert "file-sharing" in result.label.lower()
            assert len(result.alternatives) > 0, "Expected actionable alternatives for user"
            # Verify error classifier details
            ux = get_ux_error_details("File sharing page", url=url)
            assert ux["error_class"] == "file_sharing"
            assert len(ux["what_to_try"]) > 0
            print(f"\n[PASS] {name}: Correctly flagged as '{result.label}' with {len(result.alternatives)} next steps in {elapsed*1000:.1f}ms")

        elif expected == "unsupported_drm":
            assert result.status == "unsupported_drm"
            assert result.can_extract is False
            assert len(result.alternatives) > 0
            ux = get_ux_error_details("DRM encryption", url=url)
            assert ux["error_class"] == "drm"
            print(f"\n[PASS] {name}: Correctly flagged as '{result.label}' with alternatives in {elapsed*1000:.1f}ms")

        elif expected in ("invalid", "invalid_ssrf"):
            assert result.status == "invalid"
            assert result.can_extract is False
            assert len(result.alternatives) > 0
            print(f"\n[PASS] {name}: Correctly blocked as '{result.label}' in {elapsed*1000:.1f}ms")

    except AssertionError as e:
        print(f"\n[FAIL] {name}: {str(e)}")
        raise
