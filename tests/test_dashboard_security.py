import re

from dashboard.app import app, _is_allowed_flipkart_url, _rate_limit_store
from database import db_manager
from secret_store import set_secret
from secret_store import ENCRYPTED_PREFIX, get_secret


def test_login_and_delete_routes_require_post_and_csrf(tmp_path, monkeypatch):
    monkeypatch.setattr(db_manager, "DB_PATH", str(tmp_path / "dashboard.db"))
    db_manager.init_db()
    db_manager.update_admin_password("admin", "test-password-123")
    _rate_limit_store.clear()
    app.config.update(TESTING=True)

    client = app.test_client()
    login_page = client.get("/login")
    token_match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"', login_page.get_data(as_text=True)
    )
    assert token_match

    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "test-password-123",
            "csrf_token": token_match.group(1),
        },
    )
    assert response.status_code == 302
    assert client.get("/logout").status_code == 405

    db_manager.add_channel("@test_channel", "Test")
    assert client.get("/delete_channel/@test_channel").status_code == 405
    assert client.post("/delete_channel/@test_channel").status_code == 403

    with client.session_transaction() as user_session:
        csrf_token = user_session["csrf_token"]
    response = client.post(
        "/delete_channel/@test_channel",
        data={"csrf_token": csrf_token},
    )
    assert response.status_code == 302
    assert db_manager.get_all_channels() == []


def test_instant_post_url_allowlist_rejects_hostname_spoofing():
    assert _is_allowed_flipkart_url("https://www.flipkart.com/item/p/123")
    assert _is_allowed_flipkart_url("https://fkrt.it/example")
    assert not _is_allowed_flipkart_url("https://evil.example/?next=flipkart.com")
    assert not _is_allowed_flipkart_url("file:///etc/passwd?flipkart.com")


def test_settings_page_never_renders_stored_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(db_manager, "DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setenv("ENCRYPTION_KEY", "b" * 64)
    db_manager.init_db()
    set_secret("BOT_TOKEN", "123456:must-not-appear-in-html")
    app.config.update(TESTING=True)

    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session["logged_in"] = True
        user_session["username"] = "admin"
        user_session["csrf_token"] = "test-csrf-token"

    page = client.get("/settings").get_data(as_text=True)
    assert "must-not-appear-in-html" not in page
    assert "Configured — leave blank to keep" in page


def test_settings_save_uses_private_key_when_process_environment_loses_it(tmp_path, monkeypatch):
    private_env = tmp_path / "private.env"
    private_env.write_text("ENCRYPTION_KEY=" + "k" * 64 + "\n", encoding="utf-8")
    monkeypatch.setenv("DEAL_HUNTER_ENV_FILE", str(private_env))
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(db_manager, "DB_PATH", str(tmp_path / "save.db"))
    db_manager.init_db()
    app.config.update(TESTING=True)

    client = app.test_client()
    with client.session_transaction() as user_session:
        user_session.update(logged_in=True, username="admin", csrf_token="test-csrf-token")

    response = client.post(
        "/save_settings",
        data={"csrf_token": "test-csrf-token", "bot_token": "123456:dummy-only"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Settings saved securely" in response.data
    assert b"ENCRYPTION_KEY is missing" not in response.data
    assert db_manager.get_setting("BOT_TOKEN").startswith(ENCRYPTED_PREFIX)
    assert get_secret("BOT_TOKEN") == "123456:dummy-only"
