"""기기변경용 vault 내보내기(zip)·가져오기.

앱 데이터는 vault(로컬)와 로컬 config가 전부이므로 zip 하나로 기기 이동이 끝난다.
"""
from __future__ import annotations

import datetime as dt
import zipfile
from pathlib import Path
from typing import Optional

from health14 import config, vault


def export_vault(vault_path: Path, out: Optional[Path] = None) -> Path:
    """vault 전체를 zip으로 압축 (기본: <vault>/90-내보내기/)."""
    if out is None:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
        out = vault_path / vault.EXPORT_DIR / f"14health-vault-{stamp}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(vault_path.rglob("*")):
            if not file.is_file():
                continue
            rel = file.relative_to(vault_path)
            # 이전 내보내기 zip은 중첩 포함하지 않음
            if rel.parts[0] == vault.EXPORT_DIR and file.suffix == ".zip":
                continue
            zf.write(file, rel.as_posix())
    return out


def import_vault(zip_path: Path, new_vault: Path, overwrite: bool = False) -> Path:
    """zip을 새 경로에 풀고 config의 vault 경로를 갱신."""
    if not zip_path.exists():
        raise SystemExit(f"zip 파일이 없습니다: {zip_path}")
    new_vault = new_vault.expanduser()
    if new_vault.exists() and any(new_vault.iterdir()) and not overwrite:
        raise SystemExit(
            f"대상 경로가 비어있지 않습니다: {new_vault}\n"
            "기존 파일을 덮어쓰려면 --overwrite 옵션을 사용하세요.")
    new_vault.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(new_vault)
    config.set_vault_path(new_vault)
    return new_vault
