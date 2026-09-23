"""Offline regressions: no runtime credentials, database or Telegram access."""
import importlib.util
from pathlib import Path
import sys
import types
from urllib.parse import quote

import pytest


TOKEN = "1234567890:FAKE_test_token_for_regression_only"


@pytest.fixture
def isolated_bot(monkeypatch):
    config = types.ModuleType("config")
    config.BOT_TOKEN = TOKEN
    config._load_secret = lambda key: config.BOT_TOKEN
    with monkeypatch.context() as isolated:
        isolated.setitem(sys.modules, "config", config)
        spec = importlib.util.spec_from_file_location(
            "telegram_bot_security_test", Path(__file__).parents[1] / "telegram" / "bot.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    # Any unexpected HTTP access fails locally.
    def no_network(*args, **kwargs):
        raise AssertionError("Unexpected network access")
    monkeypatch.setattr(module.requests, "get", no_network)
    monkeypatch.setattr(module.requests, "post", no_network)
    return module


class Response:
    def __init__(self, payload, status=200, text="test response"):
        self.payload, self.status_code, self.text = payload, status, text

    def json(self):
        return self.payload


def invoke(bot, method, tmp_path):
    product = tmp_path / "product.jpg"
    price = tmp_path / "price.jpg"
    product.write_bytes(b"product")
    price.write_bytes(b"price")
    if method == "files":
        return bot._send_two_file_album(TOKEN, "@test", "caption", product, price)
    if method == "url_album":
        return bot._send_two_photo_album(TOKEN, "@test", "caption", "https://example.test/a.jpg", price)
    if method == "file":
        return bot._send_single_file_photo(TOKEN, "@test", "caption", price)
    if method == "url":
        return bot._send_single_url_photo(TOKEN, "@test", "caption", "https://example.test/a.jpg")
    return bot._send_text_only(TOKEN, "@test", "caption")


def test_entry_does_not_log_token_prefix(isolated_bot, monkeypatch, capsys):
    monkeypatch.setattr(isolated_bot.requests, "post", lambda *a, **k: Response({"ok": True, "result": {"message_id": 1}}))
    assert isolated_bot.send_telegram_deal_post("hello", "@test")["ok"] is True
    assert TOKEN[:10] not in capsys.readouterr().out


def test_rotated_token_is_used_without_reloading_bot(isolated_bot, monkeypatch):
    # Support both old imported snapshot and the fixed module reference.
    config = getattr(isolated_bot, "config", types.SimpleNamespace())
    monkeypatch.setattr(config, "_load_secret", lambda key: "fresh-token", raising=False)
    urls = []
    def post(url, **kwargs):
        urls.append(url)
        return Response({"ok": True, "result": {"message_id": 1}})
    monkeypatch.setattr(isolated_bot.requests, "post", post)
    assert isolated_bot.send_telegram_deal_post("hello", "@test")["ok"] is True
    assert urls == ["https://api.telegram.org/botfresh-token/sendMessage"]


@pytest.mark.parametrize("method", ["files", "url_album", "file", "url", "text"])
@pytest.mark.parametrize("source", ["exception", "response"])
def test_send_failures_never_log_token(isolated_bot, monkeypatch, tmp_path, capsys, method, source):
    sensitive = f"request https://api.telegram.org/bot{TOKEN}/sendMessage encoded={quote(TOKEN, safe='')}"
    def fail(*args, **kwargs):
        if source == "exception":
            raise isolated_bot.requests.RequestException(sensitive)
        return Response({"ok": False}, 400, sensitive)
    monkeypatch.setattr(isolated_bot.requests, "post", fail)
    assert invoke(isolated_bot, method, tmp_path) is None
    output = capsys.readouterr().out
    assert TOKEN not in output
    assert quote(TOKEN, safe="") not in output


@pytest.mark.parametrize("missing", ["product", "price", "both"])
def test_missing_production_frame_never_degrades_to_photo_or_text(isolated_bot, monkeypatch, tmp_path, missing):
    product, price = tmp_path / "product.jpg", tmp_path / "price.jpg"
    if missing not in ("product", "both"):
        product.write_bytes(b"product")
    if missing not in ("price", "both"):
        price.write_bytes(b"price")
    calls = []
    def post(*args, **kwargs):
        calls.append(args[0])
        return Response({"ok": True, "result": {"message_id": 1}})
    monkeypatch.setattr(isolated_bot.requests, "post", post)
    result = isolated_bot.send_telegram_deal_post("caption", "@test", product_image_path=product, price_screenshot_path=price)
    assert result is None
    assert calls == []


@pytest.mark.parametrize("payload", [{"ok": False}, {"ok": True}, {"ok": True, "result": {}}, {"ok": "false", "result": {"message_id": 1}}])
@pytest.mark.parametrize("method", ["file", "url", "text"])
def test_http_200_without_successful_message_is_failure(isolated_bot, monkeypatch, tmp_path, method, payload):
    monkeypatch.setattr(isolated_bot.requests, "post", lambda *a, **k: Response(payload))
    assert invoke(isolated_bot, method, tmp_path) is None


@pytest.mark.parametrize("payload", [
    {"ok": True, "result": [{}, {}]},
    {"ok": "false", "result": [{"message_id": 1}, {"message_id": 2}]},
    {"ok": True, "result": [{"message_id": 1}, {"message_id": 1}]},
    {"ok": True, "result": [{"message_id": True}, {"message_id": 2}]},
])
def test_album_requires_two_distinct_real_messages(isolated_bot, payload):
    assert isolated_bot._valid_album_response(Response(payload)) is None


def test_failed_url_album_does_not_publish_separate_messages(isolated_bot, monkeypatch, tmp_path):
    urls = []
    def post(url, **kwargs):
        urls.append(url)
        if url.endswith("/sendMediaGroup"):
            return Response({"ok": False}, 400)
        return Response({"ok": True, "result": {"message_id": 1}})
    monkeypatch.setattr(isolated_bot.requests, "post", post)
    assert invoke(isolated_bot, "url_album", tmp_path) is None
    assert len(urls) == 1
