"""Tests for the deal scoring and selection engine."""
from analyzer.deal_selector import score_deal, rank_deals, pick_best_deal


def make_deal(title="Premium Product", price="₹200", mrp="₹1000",
              discount="80% Off", rating="4.2★ (1k+ Ratings)", link=None):
    return {
        "title": title,
        "price": price,
        "mrp": mrp,
        "discount": discount,
        "rating": rating,
        "buyers_count": 5000,
        "link": link or "http://flipkart.com/test",
        "image": "http://example.com/img.jpg",
    }


class TestScoreDeal:
    def test_great_deal(self):
        """High discount + high rating = great score."""
        # price=200, mrp=1000 → actual discount = 80%, claimed = 80%
        deal = make_deal(price="₹200", mrp="₹1000", discount="80% Off", rating="4.5★ (10k+ Ratings)")
        s = score_deal(deal, required_discount=60, category_priority_weight=2)
        assert s['total'] >= 85
        assert not s['reject_reason']

    def test_below_min_discount(self):
        """Discount below minimum should reject."""
        deal = make_deal(price="₹800", mrp="₹1000", discount="20% Off", rating="4.0★ (1k+ Ratings)")
        s = score_deal(deal, required_discount=60, category_priority_weight=2)
        assert s['reject_reason']

    def test_low_rating_rejection(self):
        """Rating below 4.0 should reject."""
        deal = make_deal(price="₹300", mrp="₹1000", discount="70% Off", rating="3.0★ (1k+ Ratings)")
        s = score_deal(deal, required_discount=60, category_priority_weight=2)
        assert s['reject_reason']

    def test_no_rating_allowed_with_high_discount(self):
        """No rating but very high discount should still score."""
        # price=150, mrp=1000 → actual=85%, claimed=85%
        deal = make_deal(price="₹150", mrp="₹1000", discount="85% Off", rating="")
        s = score_deal(deal, required_discount=60, category_priority_weight=2)
        assert not s['reject_reason']
        assert s['total'] > 0

    def test_title_red_flag(self):
        """Refurbished items should be rejected."""
        deal = make_deal(title="Refurbished Phone", price="₹300", mrp="₹1000", discount="70% Off")
        s = score_deal(deal, required_discount=60)
        assert s['reject_reason']

    def test_category_priority_boost(self):
        """HIGH priority should add boost."""
        deal = make_deal(price="₹300", mrp="₹1000", discount="70% Off", rating="4.5★")
        s_low = score_deal(deal, required_discount=60, category_priority_weight=1)
        s_high = score_deal(deal, required_discount=60, category_priority_weight=4)
        assert s_high['total'] > s_low['total']

    def test_savings_bonus(self):
        """High MRP savings should boost score."""
        deal_high = make_deal(mrp="₹10000", price="₹5000", discount="50% Off", rating="4.2★")
        deal_low = make_deal(mrp="₹200", price="₹100", discount="50% Off", rating="4.2★")
        s_high = score_deal(deal_high)
        s_low = score_deal(deal_low)
        assert s_high['savings_pts'] >= 70  # ₹5000 saved
        assert s_low['savings_pts'] <= 50   # ₹100 saved


class TestRankDeals:
    def test_rank_empty(self):
        """Empty list should return empty."""
        assert rank_deals([]) == []

    def test_rank_orders_correctly(self):
        """Best deal should be first."""
        deals = [
            # Decent: price=350, mrp=1000 → actual=65%, claimed=65%
            make_deal(title="Decent Deal", price="₹350", mrp="₹1000", discount="65% Off", rating="4.0★"),
            # Great: price=150, mrp=1000 → actual=85%, claimed=85%
            make_deal(title="Great Deal", price="₹150", mrp="₹1000", discount="85% Off", rating="4.8★"),
        ]
        ranked = rank_deals(deals, required_discount=60)
        assert len(ranked) > 0
        # Great should rank higher than Decent
        great_idx = next(i for i, r in enumerate(ranked) if r['deal']['title'] == 'Great Deal')
        decent_idx = next(i for i, r in enumerate(ranked) if r['deal']['title'] == 'Decent Deal')
        assert great_idx < decent_idx

    def test_rank_filters_rejected(self):
        """Rejected deals should be removed."""
        deals = [
            make_deal(title="Good Deal", price="₹200", mrp="₹1000", discount="80% Off", rating="4.5★"),
            make_deal(title="Refurbished Junk", price="₹200", mrp="₹1000", discount="80% Off", rating="4.5★"),
        ]
        ranked = rank_deals(deals, required_discount=60)
        titles = [r['deal']['title'] for r in ranked]
        assert 'Refurbished Junk' not in titles
        assert 'Good Deal' in titles


class TestPickBestDeal:
    def test_pick_empty(self):
        """None when no deals."""
        assert pick_best_deal([]) is None

    def test_pick_skips_repeated(self):
        """Deals with already-sent links should be skipped."""
        sent_links = set()

        def skip_fn(link):
            return link in sent_links

        deals = [
            make_deal(title="Already Sent", link="http://sent", price="₹200", mrp="₹1000"),
            make_deal(title="New Deal", link="http://new", price="₹200", mrp="₹1000", discount="80% Off", rating="4.5★"),
        ]
        sent_links.add("http://sent")
        result = pick_best_deal(deals, skip_link_fn=skip_fn)
        assert result is not None
        assert result['deal']['title'] == 'New Deal'
