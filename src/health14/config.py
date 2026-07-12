"""로컬 설정 관리 (~/.config/14health/config.yaml).

설정 파일에는 vault 경로, 실명→관계호칭 별칭, 노션 토큰만 담는다.
건강 수치는 절대 이 파일에 저장하지 않는다.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "14health"


def config_path() -> Path:
    override = os.environ.get("HEALTH14_CONFIG")
    if override:
        return Path(override)
    return config_dir() / "config.yaml"


def load_config() -> Dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(cfg: Dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=True)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def get_vault_path(required: bool = True) -> Optional[Path]:
    cfg = load_config()
    vault = os.environ.get("HEALTH14_VAULT") or cfg.get("vault")
    if not vault:
        if required:
            raise SystemExit(
                "vault 경로가 설정되지 않았습니다. 먼저 실행하세요:\n"
                "  14health init --vault <옵시디안 vault 경로>"
            )
        return None
    return Path(vault).expanduser()


def suggested_vault_path() -> str:
    """앱 최초화면에 프리필할 기본 vault 경로 제안."""
    return str(Path.home() / "Documents" / "14health-vault")


def set_vault_path(path: Path) -> None:
    cfg = load_config()
    cfg["vault"] = str(Path(path).expanduser().resolve())
    save_config(cfg)


def get_aliases() -> Dict[str, str]:
    """실명 → 관계호칭 매핑 (로컬 config에만 존재, vault에는 저장 안 함)."""
    return dict(load_config().get("aliases") or {})


def add_alias(name: str, relation: str) -> None:
    cfg = load_config()
    aliases = cfg.setdefault("aliases", {})
    aliases[name] = relation
    save_config(cfg)
