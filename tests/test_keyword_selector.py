import random

from analyzer.keyword_selector import (
    keyword_score,
    record_keyword_result,
    select_smart_keywords,
)


def test_priority_and_good_history_raise_score():
    now = 1_000_000
    weights = {"good": 4, "weak": 1}
    stats = {
        "good": {"attempts": 4, "deals": 6, "last_selected": now - 3600},
        "weak": {"attempts": 4, "deals": 0, "last_selected": now - 3600},
    }
    assert keyword_score("good", weights, stats, now) > keyword_score("weak", weights, stats, now)


def test_selection_diversifies_categories():
    pool = ["shirt", "jeans", "phone", "laptop"]
    categories = {"shirt": "fashion", "jeans": "fashion", "phone": "electronics", "laptop": "electronics"}
    result = select_smart_keywords(
        pool, 2, {k: 2 for k in pool}, {}, categories,
        now=1_000_000, rng=random.Random(4),
    )
    assert categories[result[0]] != categories[result[1]]


def test_result_history_updates_safely():
    stats = {}
    record_keyword_result(stats, "shoes", 2, selected_at=100)
    record_keyword_result(stats, "shoes", 0, selected_at=200)
    assert stats["shoes"]["attempts"] == 2
    assert stats["shoes"]["deals"] == 2
    assert stats["shoes"]["successes"] == 1
