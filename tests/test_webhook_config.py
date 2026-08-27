"""New in Phase 6: characterizes bot._webhook_config()'s pure decision logic
-- selecting polling vs webhook mode from env vars -- without starting a
real HTTP server."""

import pytest

import bot


def test_defaults_to_polling_mode_when_unset(monkeypatch):
    monkeypatch.delenv("WEBHOOK_MODE", raising=False)
    assert bot._webhook_config() is None


@pytest.mark.parametrize("falsy", ["false", "0", "no", "anything-else"])
def test_falsy_webhook_mode_values_mean_polling(monkeypatch, falsy):
    monkeypatch.setenv("WEBHOOK_MODE", falsy)
    assert bot._webhook_config() is None


def test_enabled_without_webhook_url_raises(monkeypatch):
    monkeypatch.setenv("WEBHOOK_MODE", "true")
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    with pytest.raises(SystemExit, match="WEBHOOK_URL"):
        bot._webhook_config()


@pytest.mark.parametrize("truthy", ["true", "1", "yes", "TRUE", "Yes"])
def test_truthy_values_enable_webhook_mode(monkeypatch, truthy):
    monkeypatch.setenv("WEBHOOK_MODE", truthy)
    monkeypatch.setenv("WEBHOOK_URL", "https://example.com")
    config = bot._webhook_config()
    assert config is not None


def test_webhook_url_is_joined_with_path(monkeypatch):
    monkeypatch.setenv("WEBHOOK_MODE", "true")
    monkeypatch.setenv("WEBHOOK_URL", "https://example.com/")
    monkeypatch.setenv("WEBHOOK_PATH", "/telegram-webhook")

    config = bot._webhook_config()

    assert config["webhook_url"] == "https://example.com/telegram-webhook"
    assert config["url_path"] == "/telegram-webhook"


def test_webhook_defaults_listen_and_port(monkeypatch):
    monkeypatch.setenv("WEBHOOK_MODE", "true")
    monkeypatch.setenv("WEBHOOK_URL", "https://example.com")
    monkeypatch.delenv("WEBHOOK_LISTEN", raising=False)
    monkeypatch.delenv("WEBHOOK_PORT", raising=False)

    config = bot._webhook_config()

    assert config["listen"] == "0.0.0.0"
    assert config["port"] == 8443


def test_webhook_listen_and_port_are_configurable(monkeypatch):
    monkeypatch.setenv("WEBHOOK_MODE", "true")
    monkeypatch.setenv("WEBHOOK_URL", "https://example.com")
    monkeypatch.setenv("WEBHOOK_LISTEN", "127.0.0.1")
    monkeypatch.setenv("WEBHOOK_PORT", "9000")

    config = bot._webhook_config()

    assert config["listen"] == "127.0.0.1"
    assert config["port"] == 9000
