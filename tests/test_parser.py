"""Tests for the shared card parser."""
from scraper.parser import (
    extract_prices_and_discount,
    extract_rating,
    extract_image,
    extract_highlights,
    is_out_of_stock,
    qualifies,
    parse_compact_count,
)


class MockCard:
    """Mock Playwright card element for testing.
    Returns a newline-separated string from inner_text (like Playwright does).
    """
    def __init__(self, text, html=""):
        if isinstance(text, list):
            self._text = "\n".join(text)
        else:
            self._text = text
        self._html = html

    def inner_text(self, timeout=5000):
        return self._text


class TestPricesAndDiscount:
    def test_extract_basic(self):
        card = MockCard("Product\n₹500\n₹1,000\n50% off")
        result = extract_prices_and_discount(card)
        assert result["price"] == "₹500"
        assert result["mrp"] == "₹1,000"
        assert result["discount_int"] == 50

    def test_extract_no_discount(self):
        card = MockCard("Product\n₹500\n₹1,000")
        result = extract_prices_and_discount(card)
        assert result["price"] == "₹500"
        assert result["mrp"] == "₹1,000"
        assert result["discount_int"] == 0

    def test_extract_single_price(self):
        card = MockCard("Product\n₹500")
        result = extract_prices_and_discount(card)
        assert result["price"] == "₹500"
        assert result["mrp"] == "Check Link"

    def test_extract_no_prices(self):
        card = MockCard("No prices here")
        result = extract_prices_and_discount(card)
        assert result["price"] == "Check Link"
        assert result["mrp"] == "Check Link"


class TestRating:
    def test_standard_rating(self):
        card = MockCard(["Product", "4.2 (1,234 Ratings)", "₹500"])
        result = extract_rating(card)
        assert result["rating_float"] == 4.2
        assert result["rating_count"] == 1234

    def test_rating_with_star(self):
        card = MockCard(["Product", "4.5★ (5k+ Ratings)"])
        result = extract_rating(card)
        assert result["rating_float"] == 4.5
        assert result["rating_count"] == 5000

    def test_rating_with_compact_count_without_parentheses(self):
        card = MockCard(["Product", "4.3", "12.5K Ratings & 900 Reviews"])
        result = extract_rating(card)
        assert result["rating_float"] == 4.3
        assert result["rating_count"] == 12500

    def test_no_rating(self):
        card = MockCard(["Product", "₹500", "50% off"])
        result = extract_rating(card)
        assert result["rating_float"] == 0.0
        assert result["rating_count"] == 0

    def test_bestseller_text(self):
        """'Bestseller' text should not confuse extraction."""
        from analyzer.deal_selector import _parse_rating
        assert _parse_rating("Bestseller") == 0.0


class TestOutOfStock:
    def test_in_stock(self):
        assert not is_out_of_stock("Product available ₹500")

    def test_out_of_stock(self):
        assert is_out_of_stock("This product is out of stock")

    def test_sold_out(self):
        assert is_out_of_stock("Sold out item")

    def test_available(self):
        assert not is_out_of_stock("Best product ever ₹999")


def test_parse_compact_count():
    assert parse_compact_count("1,234") == 1234
    assert parse_compact_count("5k") == 5000
    assert parse_compact_count("1.2M") == 1_200_000


class TestQualifies:
    def test_high_rating_high_discount(self):
        assert qualifies(4.5, 70, 60)

    def test_low_rating(self):
        assert not qualifies(3.0, 70, 60)

    def test_low_discount(self):
        assert not qualifies(4.0, 30, 60)

    def test_unrated_high_discount(self):
        """Unrated (0.0) but high discount should pass."""
        assert qualifies(0.0, 80, 60)

    def test_barely_qualifies(self):
        assert qualifies(4.0, 60, 60)
