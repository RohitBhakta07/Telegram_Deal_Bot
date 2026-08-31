from scraper.flipkart import (
    _collapse_adjacent_word_repeats,
    _extract_aggregate_rating,
    _extract_primary_price_context,
    _extract_product_schema,
)


def test_aggregate_rating_ignores_histogram_and_reviews():
    html = '''
    "individualRatingsCount":[{"ratingValue":1,"ratingCount":96}],
    "aggregateRating":{"ratingValue":4.1,"reviewCount":104,
    "ratingCount":1467,"@type":"AggregateRating"},
    "reviewRating":{"ratingValue":5}
    '''
    assert _extract_aggregate_rating(html) == (4.1, 1467)


def test_visible_rating_fallback():
    assert _extract_aggregate_rating("", "Product rating 4.4 ★") == (4.4, 0)


def test_product_schema_ignores_unrelated_price_and_review():
    html = '''
    <script type="application/ld+json">
    {"@graph":[{"@type":"Review","reviewRating":{"ratingValue":1},"price":135},
    {"@type":"Product","name":"Watch","image":"https://example.com/watch.jpg",
    "offers":{"@type":"Offer","price":359},
    "aggregateRating":{"ratingValue":4.1,"ratingCount":1467}}]}
    </script>
    '''
    schema = _extract_product_schema(html)
    assert schema["name"] == "Watch"
    assert schema["offers"]["price"] == 359
    assert schema["aggregateRating"]["ratingValue"] == 4.1


def test_collapses_adjacent_repeated_marketplace_title_phrase():
    title = (
        "SHRISYAMEN Arabic Numeral Series Unisex Watch "
        "Arabic Numeral Series Unisex Watch Analog Watch"
    )
    assert _collapse_adjacent_word_repeats(title) == (
        "SHRISYAMEN Arabic Numeral Series Unisex Watch Analog Watch"
    )


def test_price_context_does_not_take_similar_product_mrp():
    text = (
        "Hot Deal 86% 999 ₹135 Min order quantity is 3 units "
        "Similar Products 88% OFF ₹2,999 ₹359"
    )
    assert _extract_primary_price_context(text, "₹135") == ("₹999", "86% Off")
