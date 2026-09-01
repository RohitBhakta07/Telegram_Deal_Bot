"""Tests for fake/inflated discount detection."""
from analyzer.fake_drop import is_genuine_deal, get_fake_drop_reason


class TestFakeDrop:
    def test_genuine_deal(self):
        """Normal healthy deal should pass."""
        assert is_genuine_deal("Wireless Mouse", "₹500", "₹1000", "50%")

    def test_fake_mrp(self):
        """90%+ off on expensive item should fail."""
        ok, reason = get_fake_drop_reason("Laptop", "₹999", "₹99999", "99%")
        assert not ok
        assert "fake" in reason.lower() or "suspicious" in reason.lower()

    def test_price_not_below_mrp(self):
        """Price >= MRP should fail."""
        assert not is_genuine_deal("Item", "₹500", "₹500", "50%")

    def test_missing_prices(self):
        """Missing MRP or price should fail."""
        assert not is_genuine_deal("Item", "₹0", "₹0", "50%")
        assert not is_genuine_deal("Item", "N/A", "N/A", "50%")

    def test_inflated_percent_small_item(self):
        """Cheap item with huge % should fail."""
        ok, reason = get_fake_drop_reason("Cable", "₹20", "₹100", "80%")
        assert not ok
        assert "inflated" in reason.lower() or "cheap" in reason.lower()

    def test_discount_mismatch(self):
        """Claimed vs actual discount mismatch >12% should fail."""
        ok, reason = get_fake_drop_reason("Shoes", "₹700", "₹1000", "80%")
        # actual = 30%, claimed = 80%, diff = 50% > 12%
        assert not ok

    def test_spam_title(self):
        """Refurbished/damaged keywords should fail."""
        assert not is_genuine_deal("Refurbished Phone", "₹5000", "₹10000", "50%")
        assert not is_genuine_deal("Damaged Box Item", "₹500", "₹1000", "50%")
        assert not is_genuine_deal("Without Warranty Gadget", "₹500", "₹1000", "50%")

    def test_short_title(self):
        """Very short title should fail."""
        assert not is_genuine_deal("Hi", "₹500", "₹1000", "50%")


class TestParseHelpers:
    def test_zero_handling(self):
        """Should handle zero/None values gracefully."""
        ok, reason = get_fake_drop_reason("Test Item", "0", "0", "0")
        assert not ok
