import os
import sys
import tempfile

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_price_selectors_defined():
    from scraper.price_screenshot import _PRICE_BLOCK_SELECTORS
    assert isinstance(_PRICE_BLOCK_SELECTORS, list)
    assert len(_PRICE_BLOCK_SELECTORS) >= 7
    assert all(isinstance(s, str) for s in _PRICE_BLOCK_SELECTORS)


def test_price_selectors_include_new_ones():
    from scraper.price_screenshot import _PRICE_BLOCK_SELECTORS
    selectors_text = " ".join(_PRICE_BLOCK_SELECTORS)
    assert "price" in selectors_text.lower() or "_30jeq" in selectors_text


def test_ensure_dir_creates_folder():
    from scraper.price_screenshot import _ensure_dir, SCREENSHOT_DIR
    test_dir = os.path.join(tempfile.gettempdir(), "test_screenshots")
    import scraper.price_screenshot as ps
    original_dir = ps.SCREENSHOT_DIR
    try:
        ps.SCREENSHOT_DIR = test_dir
        ps._ensure_dir()
        assert os.path.isdir(test_dir)
    finally:
        ps.SCREENSHOT_DIR = original_dir
        if os.path.isdir(test_dir):
            os.rmdir(test_dir)


def test_cleanup_screenshot_removes_file():
    from scraper.price_screenshot import cleanup_screenshot
    with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as f:
        temp_path = f.name
    assert os.path.isfile(temp_path)
    cleanup_screenshot(temp_path)
    assert not os.path.isfile(temp_path)


def test_cleanup_screenshot_none_path():
    from scraper.price_screenshot import cleanup_screenshot
    cleanup_screenshot(None)
    cleanup_screenshot("")


def test_capture_returns_none_for_non_flipkart():
    from scraper.price_screenshot import capture_price_tag_screenshot
    result = capture_price_tag_screenshot("https://amazon.in/product")
    assert result is None


def test_capture_returns_none_for_empty():
    from scraper.price_screenshot import capture_price_tag_screenshot
    result = capture_price_tag_screenshot("")
    assert result is None


def test_capture_returns_none_for_none():
    from scraper.price_screenshot import capture_price_tag_screenshot
    result = capture_price_tag_screenshot(None)
    assert result is None
