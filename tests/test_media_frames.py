from PIL import Image

from telegram import media_frames


def test_matching_portrait_frames(monkeypatch, tmp_path):
    product = Image.new("RGB", (600, 800), "white")
    screenshot = tmp_path / "proof.png"
    Image.new("RGB", (900, 480), "#eeeeee").save(screenshot)
    monkeypatch.setattr(media_frames, "FRAME_DIR", str(tmp_path / "frames"))
    monkeypatch.setattr(media_frames, "_download_product_image", lambda url: product)
    deal = {
        "title": "Professional Test Product",
        "image": "https://example.com/product.jpg",
        "price": "₹599",
        "mrp": "₹1,999",
        "discount": "70% Off",
        "rating": "4.4★ (12,300 Ratings)",
    }
    first, second = media_frames.build_telegram_frames(deal, str(screenshot))
    assert Image.open(first).size == (1080, 1350)
    assert Image.open(second).size == (1080, 1350)
