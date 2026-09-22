import importlib
import sqlite3
import threading
import queue
from unittest.mock import Mock

import pytest

from database import db_manager
from secret_store import get_secret


def test_first_start_can_load_config_before_database_initialization(tmp_path, monkeypatch):
    monkeypatch.setattr(db_manager, 'DB_PATH', str(tmp_path / 'empty.db'))
    monkeypatch.delenv('BOT_TOKEN', raising=False)
    assert get_secret('BOT_TOKEN') == ''


def test_other_database_errors_are_not_hidden(monkeypatch):
    monkeypatch.delenv('BOT_TOKEN', raising=False)
    monkeypatch.setattr(db_manager, 'get_setting', Mock(side_effect=sqlite3.OperationalError('database is locked')))
    with pytest.raises(sqlite3.OperationalError):
        get_secret('BOT_TOKEN')


def test_password_policy_rejects_bcrypt_byte_overflow():
    assert not db_manager.validate_admin_password('a' * 72 + '1')[0]
    assert not db_manager.validate_admin_password('é' * 36 + '1')[0]


def test_health_reports_database_failure_as_http_failure(monkeypatch):
    dashboard = importlib.import_module('dashboard.app')
    monkeypatch.setattr(db_manager, 'get_setting', Mock(side_effect=sqlite3.OperationalError()))
    assert dashboard.app.test_client().get('/health').status_code == 503


def test_console_treats_product_log_content_as_text(tmp_path, monkeypatch):
    dashboard = importlib.import_module('dashboard.app')
    monkeypatch.setattr(dashboard, 'parent_dir', str(tmp_path))
    (tmp_path / 'bot.log').write_text('<img src=x onerror=alert(1)>', encoding='utf8')
    client = dashboard.app.test_client()
    with client.session_transaction() as sess:
        sess['logged_in'] = True
    response = client.get('/get_logs')
    assert response.mimetype == 'text/plain'
    assert 'logContent.textContent = data' in client.get('/live_console').text


def test_affiliate_failure_holds_post_and_fallback_uses_latest_settings(monkeypatch):
    links = importlib.import_module('affiliate_links')
    monkeypatch.setattr(links, 'get_sync_link', lambda url: url)
    settings = {}
    monkeypatch.setattr(links.config, '_load_secret', lambda key: settings.get(key, ''))
    url = 'https://www.flipkart.com/item/p/123?pid=ABC'
    assert links.get_affiliate_link(url) is None
    settings['EXTRAPE_AFFID'] = 'our-account'
    assert 'affid=our-account' in links.get_affiliate_link(url)
    assert links.get_affiliate_link('https://fkrt.it/short') is None
    assert links.get_affiliate_link('https://evil.example/item') is None


def test_partial_channel_failure_retries_only_failed_channel(tmp_path, monkeypatch):
    publishing = importlib.import_module('publishing')
    monkeypatch.setattr(db_manager, 'DB_PATH', str(tmp_path / 'delivery.db'))
    db_manager.init_db()
    db_manager.add_channel('@one', 'One')
    db_manager.add_channel('@two', 'Two')
    deal = {'title': 'Verified product', 'link': 'https://www.flipkart.com/item', 'image': ''}
    sender = Mock(side_effect=[True, None, True])
    monkeypatch.setattr(publishing, 'post_deal_message', sender)
    publishing.publish_deal(deal, 'message', 'affiliate', 'Test', 'normal')
    assert not db_manager.is_link_already_sent(deal['link'])
    publishing.publish_deal(deal, 'message', 'affiliate', 'Test', 'normal')
    assert db_manager.is_link_already_sent(deal['link'])
    assert [call.args[1] for call in sender.call_args_list] == ['@one', '@two', '@two']


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(db_manager, 'DB_PATH', str(tmp_path / 'pipeline.db'))
    db_manager.init_db()
    main = importlib.import_module('main')
    monkeypatch.setattr(main, 'cleanup_thread', Mock())
    monkeypatch.setattr(main, 'cleanup_deal_media', Mock())
    return main


def queued_deal():
    pending = queue.PriorityQueue()
    item = {'deal': {'title': 'Test product', 'link': 'https://www.flipkart.com/item',
                     'price': '999', 'mrp': '1999', 'discount': '50%', 'image': ''},
            'score': {'total': 80}, 'keyword': 'test', 'category': 'Test', 'post_format': 'hot_deal'}
    pending.put((2, 1, item))
    return pending, item


@pytest.mark.parametrize('failure', [True, False])
def test_consumer_holds_failed_affiliate_and_always_completes_queue(pipeline, monkeypatch, failure):
    pending, item = queued_deal()
    stop = threading.Event()
    monkeypatch.setattr(stop, 'wait', lambda *_: stop.set())
    monkeypatch.setattr(pipeline, 'get_affiliate_link', Mock(side_effect=RuntimeError()) if failure else Mock(return_value=None))
    sender = Mock()
    monkeypatch.setattr(pipeline, '_post_single_deal', sender)
    pipeline.consumer_thread(pending, stop)
    assert pending.unfinished_tasks == 0
    sender.assert_not_called()
    pipeline.cleanup_deal_media.assert_called_once_with(item['deal'])


def test_paused_consumer_does_not_dequeue(pipeline, monkeypatch):
    pending, _ = queued_deal()
    db_manager.update_setting('bot_status', 'OFF')
    stop = threading.Event()
    monkeypatch.setattr(stop, 'wait', lambda *_: stop.set())
    pipeline.consumer_thread(pending, stop)
    assert pending.qsize() == 1


def test_queue_to_affiliate_caption_to_channel_history(pipeline, monkeypatch):
    publishing = importlib.import_module('publishing')
    pending, item = queued_deal()
    db_manager.add_channel('@test', 'Test')
    affiliate = 'https://fkrt.co/test-affiliate'
    monkeypatch.setattr(pipeline, 'get_affiliate_link', lambda _: affiliate)
    delivery = Mock(return_value={'ok': True, 'result': [{'message_id': 1}, {'message_id': 2}]})
    monkeypatch.setattr(publishing, 'post_deal_message', delivery)
    stop = threading.Event()
    monkeypatch.setattr(stop, 'wait', lambda *_: stop.set())
    pipeline.consumer_thread(pending, stop)
    assert affiliate in delivery.call_args.args[2]
    assert db_manager.is_link_already_sent(item['deal']['link'])
    assert pending.unfinished_tasks == 0


def test_scrape_worker_releases_browser_on_failure(pipeline, monkeypatch):
    monkeypatch.setattr(pipeline, 'scrape_keyword_full', Mock(side_effect=RuntimeError()))
    with pytest.raises(RuntimeError):
        pipeline.scrape_worker('keyword')
    pipeline.cleanup_thread.assert_called_once()


def test_restart_requires_worker_and_sets_its_stop_event():
    import runtime_control
    runtime_control.detach()
    assert runtime_control.request_restart() is False
    stop = threading.Event()
    runtime_control.attach(stop)
    try:
        assert runtime_control.request_restart() is True
        assert stop.is_set()
        assert runtime_control.consume_restart() is True
        assert runtime_control.consume_restart() is False
    finally:
        runtime_control.detach()


def test_invalid_settings_rejected_before_any_writes(monkeypatch):
    dashboard = importlib.import_module('dashboard.app')
    setter = Mock()
    monkeypatch.setattr(db_manager, 'update_setting', setter)
    client = dashboard.app.test_client()
    with client.session_transaction() as sess:
        sess.update(logged_in=True, csrf_token='test')
    result = client.post('/save_settings', data={'csrf_token': 'test', 'max_workers': '-5'})
    assert result.status_code == 400
    setter.assert_not_called()


def test_delivery_history_expires_with_deal_history(tmp_path, monkeypatch):
    monkeypatch.setattr(db_manager, 'DB_PATH', str(tmp_path / 'expiry.db'))
    db_manager.init_db()
    db_manager.add_channel('@one', 'One')
    db_manager.record_channel_delivery('product', '@one')
    db_manager.save_deal('Product', 'product', 'affiliate')
    assert db_manager.delete_oldest_deals(1) == 1
    assert not db_manager.is_link_already_sent('product')
    assert db_manager.delivered_channels('product') == set()


def test_documented_placeholder_is_never_accepted_as_encryption_key(monkeypatch):
    from secret_store import encrypt_secret, SecretConfigurationError
    monkeypatch.setenv('ENCRYPTION_KEY', 'generate_at_least_32_random_characters')
    with pytest.raises(SecretConfigurationError):
        encrypt_secret('value')


def test_round_wait_applies_adaptive_flash_interval(pipeline, monkeypatch):
    clock = [0]
    stop = threading.Event()
    monkeypatch.setattr(pipeline.time, 'monotonic', lambda: clock[0])
    def wait(seconds):
        clock[0] += seconds
        return False
    monkeypatch.setattr(stop, 'wait', wait)
    checks = []
    def flash(_):
        checks.append(clock[0])
        return 20
    monkeypatch.setattr(pipeline, 'check_flash_sales', flash)
    pipeline.wait_between_rounds(queue.PriorityQueue(), stop, 55, 10)
    assert checks == [10, 30, 50]


def test_worker_exception_joins_consumer_before_restarting(pipeline, monkeypatch):
    monkeypatch.setattr(pipeline.signal, 'signal', Mock())
    poster = Mock()
    monkeypatch.setattr(pipeline.threading, 'Thread', Mock(return_value=poster))
    monkeypatch.setattr(pipeline, '_run_rounds', Mock(side_effect=RuntimeError()))
    with pytest.raises(RuntimeError):
        pipeline.run_bot()
    poster.join.assert_called_once()
