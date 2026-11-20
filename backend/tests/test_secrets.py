from cat_dash import secrets
from cat_dash.config import Settings
from cat_dash.secrets_cli import main


def test_password_from_keychain(monkeypatch):
    monkeypatch.setenv("CATDASH_PETLIBRO_EMAIL", "me@example.com")
    monkeypatch.delenv("CATDASH_PETLIBRO_PASSWORD", raising=False)
    settings = Settings(_env_file=None)
    assert not settings.petlibro_configured

    secrets.set_password("petlibro", "me@example.com", "s3cret")
    assert settings.petlibro_password_value() == "s3cret"
    assert settings.petlibro_configured


def test_env_password_overrides_keychain(monkeypatch):
    monkeypatch.setenv("CATDASH_LITTERROBOT_USERNAME", "me@example.com")
    monkeypatch.setenv("CATDASH_LITTERROBOT_PASSWORD", "from-env")
    secrets.set_password("litterrobot", "me@example.com", "from-keychain")
    assert Settings(_env_file=None).litterrobot_password_value() == "from-env"


def test_cli_set_check_delete(monkeypatch, capsys, memory_keyring):
    monkeypatch.setenv("CATDASH_PETLIBRO_EMAIL", "me@example.com")
    monkeypatch.setattr("cat_dash.secrets_cli.Settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr("getpass.getpass", lambda prompt: "pw")
    assert main(["set", "petlibro"]) == 0
    assert memory_keyring.store[("cat-dash", "petlibro:me@example.com")] == "pw"
    main(["check"])
    out = capsys.readouterr().out
    assert "petlibro: password found" in out and "pw\n" not in out
    assert main(["delete", "petlibro"]) == 0
    assert secrets.get_password("petlibro", "me@example.com") is None
