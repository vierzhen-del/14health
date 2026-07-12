"""입력 결과의 MD 내보내기/읽어오기.

vault 노트는 이미 자립형 md(frontmatter 포함)이므로 내보내기는 복사,
읽어오기는 frontmatter 노트면 그대로 저장하고 비정형 md는 파싱 결과를
돌려주어 사용자 확인을 거치게 한다.
"""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from health14 import intake, parse, vault


def export_member_md(vault_path: Path, relation: str,
                     out_dir: Optional[Path] = None) -> List[Path]:
    """구성원의 검진·진료·분석 노트를 90-내보내기/ 하위 폴더로 복사."""
    if vault.get_member(vault_path, relation) is None:
        raise SystemExit(f"등록되지 않은 구성원입니다: {relation}")
    member_dir = vault_path / vault.MEMBERS_DIR / relation
    if out_dir is None:
        stamp = dt.date.today().strftime("%Y%m%d")
        out_dir = vault_path / vault.EXPORT_DIR / f"md-{relation}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    copied: List[Path] = []
    for sub in ("검진", "진료", "분석"):
        folder = member_dir / sub
        if not folder.exists():
            continue
        for f in sorted(folder.glob("*.md")):
            dest = out_dir / f"{sub}-{f.name}"
            shutil.copy2(f, dest)
            copied.append(dest)
    profile = member_dir / "프로필.md"
    if profile.exists():
        dest = out_dir / "프로필.md"
        shutil.copy2(profile, dest)
        copied.append(dest)
    return copied


def import_md_content(vault_path: Path, content: str,
                      relation: Optional[str] = None,
                      confirm_only: bool = False) -> Dict[str, Any]:
    """md 내용을 해석해 저장하거나(우리 형식) 파싱 미리보기를 반환(비정형).

    반환: {saved: bool, kind, data, path?}
    """
    result = parse.parse_md_content(content)
    kind, data = result["kind"], result["data"]
    if kind == "other":
        return {"saved": False, "kind": kind, "data": data,
                "error": f"{data.get('type')} 노트는 재입력 대상이 아닙니다."}
    target = relation or data.get("relation")

    if kind in ("checkup", "visit") and not confirm_only:
        if not target:
            return {"saved": False, "kind": kind, "data": data,
                    "error": "관계호칭을 알 수 없습니다. relation을 지정하세요."}
        if kind == "checkup":
            path = intake.apply_checkup(vault_path, target, data)
        else:
            path = intake.apply_visit(vault_path, target, data)
        return {"saved": True, "kind": kind, "data": data, "path": str(path)}

    # 비정형 md → 미리보기 (사용자 확인 후 /api/note 또는 note write로 저장)
    data["relation"] = target
    return {"saved": False, "kind": kind, "data": data}


def import_md_path(vault_path: Path, target: Path,
                   relation: Optional[str] = None) -> List[Dict[str, Any]]:
    """md 파일 또는 폴더를 읽어온다. 파일별 결과 목록 반환."""
    if target.is_dir():
        files = sorted(target.glob("*.md"))
    elif target.suffix.lower() == ".md":
        files = [target]
    else:
        raise SystemExit(f"md 파일이 아닙니다: {target}")
    if not files:
        raise SystemExit(f"md 파일이 없습니다: {target}")

    results = []
    for f in files:
        r = import_md_content(vault_path, f.read_text(encoding="utf-8"), relation)
        r["file"] = str(f)
        results.append(r)
    return results
