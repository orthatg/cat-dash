import pytest

from cat_dash import secrets
from cat_dash.config import Settings
from cat_dash.secrets_cli import main


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("HOST", "BLID", "PASSWORD"):
        monkeypatch.delenv(f"CATDASH_ROOMBA_{name}", raising=False)


def test_unset_means_unconfigured():
    s = Settings(_env_file=None)
    assert not s.roomba_configured
    assert s.roomba_password_value() is None


def test_placeholders_are_unset(monkeypatch):
    monkeypatch.setenv("CATDASH_ROOMBA_HOST", "CHANGE_ME")
    monkeypatch.setenv("CATDASH_ROOMBA_BLID", "CHANGE_ME")
    monkeypatch.setenv("CATDASH_ROOMBA_PASSWORD", "CHANGE_ME")
    s = Settings(_env_file=None)
    assert s.roomba_host is None and s.roomba_blid is None and s.roomba_password is None
    assert not s.roomba_configured


def test_env_password_configures(monkeypatch):
    monkeypatch.setenv("CATDASH_ROOMBA_HOST", "10.0.0.5")
    monkeypatch.setenv("CATDASH_ROOMBA_BLID", "ABC")
    monkeypatch.setenv("CATDASH_ROOMBA_PASSWORD", "pw")
    s = Settings(_env_file=None)
    assert s.roomba_password_value() == "pw" and s.roomba_configured


def test_password_from_keychain_account_roomba_blid(monkeypatch, memory_keyring):
    monkeypatch.setenv("CATDASH_ROOMBA_HOST", "10.0.0.5")
    monkeypatch.setenv("CATDASH_ROOMBA_BLID", "ABC")
    s = Settings(_env_file=None)
    assert not s.roomba_configured
    secrets.set_password("roomba", "ABC", "kc-pw")
    assert memory_keyring.store[("cat-dash", "roomba:ABC")] == "kc-pw"
    assert s.roomba_password_value() == "kc-pw" and s.roomba_configured


def test_env_password_beats_keychain(monkeypatch):
    monkeypatch.setenv("CATDASH_ROOMBA_BLID", "ABC")
    monkeypatch.setenv("CATDASH_ROOMBA_PASSWORD", "from-env")
    secrets.set_password("roomba", "ABC", "from-keychain")
    assert Settings(_env_file=None).roomba_password_value() == "from-env"


def test_host_required_for_configured(monkeypatch):
    monkeypatch.setenv("CATDASH_ROOMBA_BLID", "ABC")
    monkeypatch.setenv("CATDASH_ROOMBA_PASSWORD", "pw")
    assert not Settings(_env_file=None).roomba_configured


def test_roomba_is_a_secrets_integration():
    assert "roomba" in secrets.INTEGRATIONS


def test_cli_set_check_delete_uses_blid(monkeypatch, capsys, memory_keyring):
    monkeypatch.setenv("CATDASH_ROOMBA_BLID", "ABC")
    monkeypatch.setattr("cat_dash.secrets_cli.Settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr("getpass.getpass", lambda prompt: "robot-pw")
    assert main(["set", "roomba"]) == 0
    assert memory_keyring.store[("cat-dash", "roomba:ABC")] == "robot-pw"
    main(["check"])
    out = capsys.readouterr().out
    assert "roomba: password found" in out and "robot-pw" not in out
    assert main(["delete", "roomba"]) == 0
    assert secrets.get_password("roomba", "ABC") is None


def test_cli_set_without_blid_fails(monkeypatch):
    monkeypatch.setattr("cat_dash.secrets_cli.Settings", lambda: Settings(_env_file=None))
    assert main(["set", "roomba"]) == 1
