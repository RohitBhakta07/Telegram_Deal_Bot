from userbot import extrape_agent


def test_get_sync_link_fallback(monkeypatch):
    # Force client to None to test fallback behavior
    monkeypatch.setattr(extrape_agent, 'client', None)
    original = 'https://example.com/product'
    result = extrape_agent.get_sync_link(original)
    assert result == original
