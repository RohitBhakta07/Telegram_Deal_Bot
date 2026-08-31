"""Tests for the ExtraPe affiliate agent."""
from userbot import extrape_agent


def test_get_sync_link_fallback(monkeypatch):
    """When Telethon is unavailable, should return original link."""
    monkeypatch.setattr(extrape_agent, 'TelegramClient', None)
    original = 'https://example.com/product'
    result = extrape_agent.get_sync_link(original)
    assert result == original


def test_get_sync_link_empty(monkeypatch):
    """Empty string should pass through."""
    monkeypatch.setattr(extrape_agent, 'TelegramClient', None)
    assert extrape_agent.get_sync_link('') == ''


def test_client_initialization_fallback(monkeypatch):
    """If Telethon is unavailable, TelegramClient is None."""
    monkeypatch.setattr(extrape_agent, 'TelegramClient', None)
    from userbot import extrape_agent as agent
    assert agent.TelegramClient is None


def test_session_directory_resolves_to_file(tmp_path):
    resolved = extrape_agent._resolve_session_file(str(tmp_path / 'sessions'))
    assert resolved.endswith('extrape')
    assert resolved != str(tmp_path / 'sessions')


def test_session_filename_does_not_get_double_suffix(tmp_path):
    resolved = extrape_agent._resolve_session_file(str(tmp_path / 'saved.session'))
    assert resolved.endswith('saved')
    assert not resolved.endswith('.session')
