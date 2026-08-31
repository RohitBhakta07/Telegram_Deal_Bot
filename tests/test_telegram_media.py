from telegram import bot
import json


class _ImageResponse:
    content = b"image-bytes" * 100
    headers = {"Content-Type": "image/jpeg"}

    def raise_for_status(self):
        return None


class _TelegramResponse:
    status_code = 200
    text = "ok"

    def json(self):
        return {"ok": True, "result": [{"message_id": 1}, {"message_id": 2}]}


def test_album_uploads_product_and_price_as_files(monkeypatch, tmp_path):
    price = tmp_path / "price.png"
    price.write_bytes(b"price-bytes" * 100)
    captured = {}

    monkeypatch.setattr(bot.requests, "get", lambda *a, **k: _ImageResponse())

    def fake_post(url, data=None, files=None, timeout=None):
        captured["files"] = set(files)
        captured["media"] = data["media"]
        return _TelegramResponse()

    monkeypatch.setattr(bot.requests, "post", fake_post)
    result = bot._send_two_photo_album(
        "token", "@channel", "caption",
        "https://rukminim.example/product.jpeg", str(price),
    )
    assert result["ok"] is True
    assert captured["files"] == {"product_photo", "price_shot"}
    assert "attach://product_photo" in captured["media"]
    assert "attach://price_shot" in captured["media"]


def test_framed_album_is_exactly_two_local_photos(monkeypatch, tmp_path):
    product = tmp_path / "product.jpg"
    price = tmp_path / "price.jpg"
    product.write_bytes(b"product-frame")
    price.write_bytes(b"price-frame")
    captured = {}

    def fake_post(url, data=None, files=None, timeout=None):
        captured["url"] = url
        captured["files"] = set(files)
        captured["media"] = json.loads(data["media"])
        return _TelegramResponse()

    monkeypatch.setattr(bot.requests, "post", fake_post)
    result = bot._send_two_file_album(
        "token", "@channel", "caption", str(product), str(price)
    )

    assert result["ok"] is True
    assert captured["url"].endswith("/sendMediaGroup")
    assert captured["files"] == {"product_frame", "price_frame"}
    assert len(captured["media"]) == 2
    assert captured["media"][0]["media"] == "attach://product_frame"
    assert captured["media"][1]["media"] == "attach://price_frame"
    assert captured["media"][0]["caption"] == "caption"


def test_framed_album_rejects_partial_telegram_result(monkeypatch, tmp_path):
    product = tmp_path / "product.jpg"
    price = tmp_path / "price.jpg"
    product.write_bytes(b"product-frame")
    price.write_bytes(b"price-frame")

    class PartialResponse(_TelegramResponse):
        def json(self):
            return {"ok": True, "result": [{"message_id": 1}]}

    monkeypatch.setattr(bot.requests, "post", lambda *a, **k: PartialResponse())
    assert bot._send_two_file_album(
        "token", "@channel", "caption", str(product), str(price)
    ) is None
