"""Tests for the ExtraPe affiliate agent."""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
from types import SimpleNamespace

import pytest

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


class ReplyClient:
    """Offline Telegram boundary: finite replies, then a conversation timeout."""

    def __init__(self, replies):
        self.replies = iter(replies)
        self.sent = []

    async def is_user_authorized(self):
        return True

    def conversation(self, username, **kwargs):
        assert username == '@ExtraPeBot'
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def send_message(self, value):
        self.sent.append(value)

    async def get_response(self):
        try:
            return next(self.replies)
        except StopIteration:
            raise asyncio.TimeoutError from None


def reply(text='', button_url=None):
    buttons = [[SimpleNamespace(url=button_url)]] if button_url else []
    return SimpleNamespace(text=text, buttons=buttons)


@pytest.mark.parametrize('url', [
    'https://fkrt.co.attacker.example/item',
    'https://attacker.example/path/fkrt.co',
    'https://fkrt.co@attacker.example/item',
    'https://user:password@fkrt.co/item',
    'https://fkrt.co:8443/item',
    'https://fkrt.co/',
    'https://t.me/marketing',
    'https://www.flipkart.com/offers',
])
def test_untrusted_or_marketing_reply_never_replaces_product(url):
    original = 'https://www.flipkart.com/item/p/123'
    client = ReplyClient([reply(url)])
    assert asyncio.run(extrape_agent._get_extrape_link(client, original)) == original


@pytest.mark.parametrize('url', [
    'https://fkrt.co/Ab12',
    'https://fkrt.it/Ab12',
    'https://www.flipkart.com/item?pid=1&affid=2',
])
def test_status_reply_is_skipped_until_trusted_affiliate_button(url):
    original = 'https://www.flipkart.com/item/p/123'
    client = ReplyClient([
        reply('Processing your request'),
        reply('Join us https://t.me/marketing'),
        reply(button_url=url),
    ])
    assert asyncio.run(extrape_agent._get_extrape_link(client, original)) == url
    assert client.sent == [original]


def test_reply_timeout_bounds_repeated_status_messages(monkeypatch):
    class SlowClient(ReplyClient):
        cancelled = False

        async def get_response(self):
            try:
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            return reply('Processing')

    monkeypatch.setattr(extrape_agent, '_REPLY_TIMEOUT', 0.005, raising=False)
    original = 'https://www.flipkart.com/item/p/123'

    async def check():
        client = SlowClient([])
        result = await extrape_agent._get_extrape_link(client, original)
        assert result == original
        assert client.cancelled

    asyncio.run(check())


def test_overlapping_requests_never_open_second_session(monkeypatch):
    async def check():
        connected = asyncio.Event()
        release = asyncio.Event()
        sessions = []

        class Session(ReplyClient):
            def __init__(self, *args):
                super().__init__([reply('https://fkrt.co/converted')])
                sessions.append(self)

            async def connect(self):
                connected.set()
                await release.wait()

            async def disconnect(self):
                pass

        monkeypatch.setattr(extrape_agent, 'TelegramClient', Session)
        monkeypatch.setattr(extrape_agent, 'API_ID', '123', raising=False)
        monkeypatch.setattr(extrape_agent, 'API_HASH', 'hash', raising=False)
        import config
        monkeypatch.setattr(config, '_load_secret', lambda key: '123' if key == 'API_ID' else 'hash')
        first = asyncio.create_task(extrape_agent._run_async('https://www.flipkart.com/one'))
        await connected.wait()
        second = asyncio.create_task(extrape_agent._run_async('https://www.flipkart.com/two'))
        await asyncio.sleep(0)
        release.set()
        first_result, second_result = await asyncio.gather(first, second)
        assert len(sessions) == 1
        assert first_result == 'https://fkrt.co/converted'
        assert second_result == 'https://www.flipkart.com/two'

    asyncio.run(check())


def test_sync_timeout_cancels_pending_conversion(monkeypatch):
    class PendingFuture:
        cancelled = False

        def result(self, timeout):
            raise FutureTimeoutError

        def cancel(self):
            self.cancelled = True

    pending = PendingFuture()

    def submit(coro, loop):
        coro.close()
        return pending

    monkeypatch.setattr(extrape_agent, 'TelegramClient', object())
    monkeypatch.setattr(extrape_agent, '_start_loop_thread', lambda: object())
    monkeypatch.setattr(asyncio, 'run_coroutine_threadsafe', submit)
    original = 'https://www.flipkart.com/item'
    assert extrape_agent.get_sync_link(original) == original
    assert pending.cancelled


def test_credentials_are_loaded_again_after_dashboard_change(monkeypatch):
    import config
    credentials = {'API_ID': '123', 'API_HASH': 'old-hash'}
    clients = []

    class Session(ReplyClient):
        def __init__(self, path, api_id, api_hash):
            super().__init__([reply('https://fkrt.co/converted')])
            clients.append((api_id, api_hash))

        async def connect(self):
            pass

        async def disconnect(self):
            pass

    monkeypatch.setattr(config, '_load_secret', lambda key: credentials[key])
    monkeypatch.setattr(extrape_agent, 'TelegramClient', Session)
    monkeypatch.setattr(extrape_agent, 'API_ID', '123', raising=False)
    monkeypatch.setattr(extrape_agent, 'API_HASH', 'old-hash', raising=False)
    asyncio.run(extrape_agent._run_async('https://www.flipkart.com/item'))
    credentials['API_HASH'] = 'new-hash'
    asyncio.run(extrape_agent._run_async('https://www.flipkart.com/item'))
    assert clients == [('123', 'old-hash'), ('123', 'new-hash')]


def test_cancelled_request_retains_session_until_disconnect_completes(monkeypatch):
    import config
    monkeypatch.setattr(config, '_load_secret', lambda key: '123' if key == 'API_ID' else 'hash')
    monkeypatch.setattr(extrape_agent, '_DISCONNECT_TIMEOUT', 0.005)

    async def check():
        connected = asyncio.Event()
        disconnect_started = asyncio.Event()
        finish_disconnect = asyncio.Event()
        sessions = []

        class Session(ReplyClient):
            def __init__(self, *args):
                super().__init__([reply('https://fkrt.co/converted')])
                sessions.append(self)

            async def connect(self):
                connected.set()
                if len(sessions) == 1:
                    await asyncio.Event().wait()

            async def disconnect(self):
                disconnect_started.set()
                await finish_disconnect.wait()

        monkeypatch.setattr(extrape_agent, 'TelegramClient', Session)
        first = asyncio.create_task(extrape_agent._run_async('https://www.flipkart.com/one'))
        await connected.wait()
        first.cancel()
        await disconnect_started.wait()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert await extrape_agent._run_async('https://www.flipkart.com/two') == 'https://www.flipkart.com/two'
        assert len(sessions) == 1
        finish_disconnect.set()
        await asyncio.gather(*tuple(extrape_agent._cleanup_tasks))
        assert await extrape_agent._run_async('https://www.flipkart.com/three') == 'https://fkrt.co/converted'
        assert len(sessions) == 2

    asyncio.run(check())


def test_hung_connection_hits_request_deadline_and_disconnects(monkeypatch):
    import config
    monkeypatch.setattr(config, '_load_secret', lambda key: '123' if key == 'API_ID' else 'hash')
    monkeypatch.setattr(extrape_agent, '_REQUEST_TIMEOUT', 0.005)
    disconnected = []

    class Session:
        def __init__(self, *args):
            pass

        async def connect(self):
            await asyncio.Event().wait()

        async def disconnect(self):
            disconnected.append(True)

    monkeypatch.setattr(extrape_agent, 'TelegramClient', Session)
    original = 'https://www.flipkart.com/item'
    assert asyncio.run(extrape_agent._run_async(original)) == original
    assert disconnected == [True]


def test_affiliate_identifiers_and_exception_details_are_not_logged(capsys):
    affiliate_url = 'https://fkrt.co/private-tracking-code'
    client = ReplyClient([reply(affiliate_url)])
    assert asyncio.run(extrape_agent._get_extrape_link(client, 'https://www.flipkart.com/item')) == affiliate_url
    assert 'private-tracking-code' not in capsys.readouterr().out

    class BrokenClient(ReplyClient):
        async def is_user_authorized(self):
            raise ValueError('private-api-hash')

    original = 'https://www.flipkart.com/item'
    assert asyncio.run(extrape_agent._get_extrape_link(BrokenClient([]), original)) == original
    assert 'private-api-hash' not in capsys.readouterr().out
