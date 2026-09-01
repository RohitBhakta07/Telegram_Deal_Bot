from telegram.post_format import build_deal_message


def test_message_shows_real_affiliate_url_and_escapes_fields():
    deal = {
        "title": "Shoes & Sandals <sale>",
        "mrp": "₹1,000",
        "price": "₹499",
        "discount": "50% Off",
        "rating": "4.3★",
    }
    url = "https://www.flipkart.com/item?pid=1&affid=2"
    message = build_deal_message(deal, url)
    assert "OPEN DEAL ON FLIPKART" not in message
    assert "https://www.flipkart.com/item?pid=1&amp;affid=2" in message
    assert "&amp;affid=2" in message
    assert "Shoes &amp; Sandals &lt;sale&gt;" in message
