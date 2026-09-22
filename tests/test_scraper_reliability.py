"""Offline regression tests for producer backpressure and browser lifetime."""
import queue
import json
from unittest.mock import Mock

import pytest

from scraper import browser_pool, flipkart
from analyzer.deal_selector import score_deal, pick_best_deal


@pytest.fixture
def scraper_inputs(monkeypatch, tmp_path):
    context = Mock()
    monkeypatch.setattr(flipkart, "new_context", lambda: context)
    deals = [dict(title=f"Premium Product {i}", link=f"https://www.flipkart.com/p/{i}",
                  price="₹200", mrp="₹1000", discount="80% Off", rating="4.5★")
             for i in range(2)]
    monkeypatch.setattr(flipkart, "scrape_search_page", lambda *args: deals)
    monkeypatch.setattr(flipkart, "deep_check_product_data", lambda *args: dict(
        rating=4.5, rating_count=2000, image="", title="", price="", mrp="", discount=""))
    paths = [tmp_path / f"proof{i}.png" for i in range(2)]
    for path in paths:
        path.write_bytes(b"proof")
    available = iter(paths)
    monkeypatch.setattr(flipkart, "capture_price_tag_screenshot", lambda *args: str(next(available)))
    return context, paths


def test_full_queue_drops_proofs_and_counts_only_enqueued(scraper_inputs):
    context, paths = scraper_inputs

    class BoundedQueue(queue.PriorityQueue):
        def put(self, item, block=True, timeout=None):
            # Fail quickly on the old unbounded call instead of hanging the test.
            assert not block or timeout is not None, "producer must not block indefinitely"
            return super().put(item, block=block, timeout=timeout)

    pending = BoundedQueue(maxsize=1)
    count = flipkart.scrape_keyword_full("headphones", dict(max_pages=1, price_screenshot_on=True), pending)
    assert count == 1
    assert pending.qsize() == 1
    assert paths[0].exists()
    assert not paths[1].exists()
    context.close.assert_called_once()


def test_flash_deals_receive_flash_priority(scraper_inputs):
    pending = queue.PriorityQueue()
    assert flipkart.scrape_keyword_full("headphones", dict(max_pages=1, is_flash=True), pending) == 2
    assert pending.get_nowait()[0] == 1
    assert pending.get_nowait()[0] == 1


def test_launch_failure_stops_playwright(monkeypatch):
    browser_pool.cleanup_thread()
    playwright = Mock()
    playwright.chromium.launch.side_effect = RuntimeError("cannot launch")
    monkeypatch.setattr(browser_pool, "sync_playwright", lambda: Mock(start=lambda: playwright))
    monkeypatch.setattr(browser_pool.os.path, "isfile", lambda path: True)
    with pytest.raises(RuntimeError, match="cannot launch"):
        browser_pool._get_or_create_browser()
    playwright.stop.assert_called_once()
    assert not hasattr(browser_pool._thread_local, "browser")


def test_disconnected_browser_is_replaced(monkeypatch):
    browser_pool.cleanup_thread()
    old_browser, old_playwright, playwright, new_browser = Mock(), Mock(), Mock(), Mock()
    old_browser.is_connected.return_value = False
    browser_pool._thread_local.browser = old_browser
    browser_pool._thread_local.playwright = old_playwright
    playwright.chromium.launch.return_value = new_browser
    monkeypatch.setattr(browser_pool, "sync_playwright", lambda: Mock(start=lambda: playwright))
    monkeypatch.setattr(browser_pool.os.path, "isfile", lambda path: True)
    try:
        assert browser_pool._get_or_create_browser() is new_browser
        old_browser.close.assert_called_once()
        old_playwright.stop.assert_called_once()
    finally:
        browser_pool.cleanup_thread()


def test_decimal_price_does_not_multiply_savings_or_reject_deal():
    deal = dict(title="Premium Product", price="₹200.00", mrp="₹1,000",
                discount="80% Off", rating="4.5★")
    result = score_deal(deal)
    assert result["savings_rupees"] == 800
    assert result["reject_reason"] is None


def test_missing_buyers_allowed_without_disabling_known_count_threshold():
    deal = dict(title="Premium Product", price="₹200", mrp="₹1000",
                discount="80% Off", rating="4.5★")
    assert pick_best_deal([deal], allow_missing_buyers=True) is not None
    assert pick_best_deal([deal], allow_missing_buyers=False) is None
    assert pick_best_deal([dict(deal, buyers_count=100)], allow_missing_buyers=True) is None


@pytest.fixture
def single_product_page(monkeypatch):
    context, page = Mock(), Mock()
    context.new_page.return_value = page
    page.url = "https://www.flipkart.com/headphones/p/itm123?pid=123"
    page.inner_text.return_value = "Wireless Headphones\n80% off ₹1,000 ₹200"
    monkeypatch.setattr(flipkart, "new_context", lambda: context)
    monkeypatch.setattr(flipkart.time, "sleep", lambda *args: None)
    return context, page


def _product_html(**overrides):
    schema = dict(**{"@type": "Product"}, name="Wireless Headphones",
                  image="https://rukminim2.flixcart.com/image/product.jpg", offers={"price": 200})
    schema.update(overrides)
    return '<script type="application/ld+json">' + json.dumps(schema) + '</script>'


@pytest.mark.parametrize("html", ["<h1>Access denied</h1>", _product_html(name=""),
                                 _product_html(offers={}), _product_html(offers={"price": 0}),
                                 _product_html(image="")])
def test_instant_product_rejects_unverified_product_data(single_product_page, html):
    context, page = single_product_page
    page.content.return_value = html
    assert flipkart.scrape_single_product("https://fkrt.it/example") is None
    context.close.assert_called_once()


def test_instant_product_uses_final_url_without_invented_highlights(single_product_page):
    context, page = single_product_page
    page.content.return_value = _product_html()
    result = flipkart.scrape_single_product("https://fkrt.it/example")
    assert result["link"] == page.url
    assert result["highlights"] == ""
    context.close.assert_called_once()


@pytest.mark.parametrize("url", ["https://flipkart.com.evil.test/p/item", "https://example.com/p/item",
                                 "https://user:password@www.flipkart.com/p/item"])
def test_instant_product_rejects_foreign_final_destination(single_product_page, url):
    context, page = single_product_page
    page.content.return_value = _product_html()
    page.url = url
    assert flipkart.scrape_single_product("https://fkrt.it/example") is None
    context.close.assert_called_once()
