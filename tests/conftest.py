import pytest

from health14 import config as config_mod
from health14 import recommend


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """테스트마다 임시 config 사용 — 실제 사용자 설정을 건드리지 않음."""
    monkeypatch.setenv("HEALTH14_CONFIG", str(tmp_path / "config.yaml"))
    yield


@pytest.fixture
def vault_path(tmp_path):
    from health14 import vault
    path = tmp_path / "vault"
    vault.init_vault(path)
    config_mod.set_vault_path(path)
    return path
