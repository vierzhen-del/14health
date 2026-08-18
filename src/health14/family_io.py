"""가족 정보 JSON 내보내기/가져오기.

구성원 목록·가족력을 하나의 JSON으로 옮긴다. 검진 수치·진료 기록은 포함하지
않는다(그건 vault zip 또는 MD 내보내기 담당).

**실명(aliases)은 기본적으로 제외**한다. 영수증 자동매칭용 실명 매핑은 로컬
설정에만 있고, 내보내기에 담으려면 include_names=True 를 명시해야 한다.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from health14 import config, relations, vault

SCHEMA_VERSION = 1
MEMBER_FIELDS = ("relation", "display", "category", "birth_year", "sex")


def build_payload(vault_path: Path, include_names: bool = False) -> Dict[str, Any]:
    """가족 정보 JSON 구조 생성."""
    members: List[Dict[str, Any]] = []
    for m in vault.load_members(vault_path):
        record = {k: m[k] for k in MEMBER_FIELDS if k in m}
        record.setdefault("display", relations.display_name(m))
        record.setdefault("category", relations.member_category(m))
        members.append(record)

    payload: Dict[str, Any] = {
        "schema": "14health-family",
        "version": SCHEMA_VERSION,
        "exported": dt.date.today().isoformat(),
        "members": members,
        "family_history": [
            {k: h.get(k, "") for k in ("relation", "disease", "note")}
            for h in vault.load_family_history(vault_path)
        ],
    }
    if include_names:
        # 실명 매핑 — 개인정보. 내보낸 파일을 안전한 곳에 보관해야 한다.
        payload["aliases"] = config.get_aliases()
        payload["contains_real_names"] = True
    return payload


def export_family(vault_path: Path, out: Optional[Path] = None,
                  include_names: bool = False) -> Path:
    if out is None:
        stamp = dt.date.today().strftime("%Y%m%d")
        out = vault_path / vault.EXPORT_DIR / f"가족정보-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(vault_path, include_names)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return out


def import_family(vault_path: Path, payload: Dict[str, Any],
                  restore_names: bool = False) -> Dict[str, Any]:
    """JSON → vault 구성원·가족력 반영. 이미 있는 구성원은 건너뛴다.

    반환 {added, skipped, history_added, aliases_added}
    """
    if payload.get("schema") != "14health-family":
        raise SystemExit("14health 가족정보 JSON이 아닙니다.")

    existing = {m["relation"] for m in vault.load_members(vault_path)}
    added, skipped = [], []
    for m in payload.get("members", []):
        relation = m.get("relation")
        if not relation:
            continue
        if relation in existing:
            skipped.append(relation)
            continue
        vault.add_member(vault_path, relation, int(m.get("birth_year") or 0),
                         m.get("sex", ""), m.get("category", ""),
                         m.get("display", ""))
        existing.add(relation)
        added.append(relation)

    known = {(h["relation"], h["disease"])
             for h in vault.load_family_history(vault_path)}
    history_added = 0
    for h in payload.get("family_history", []):
        key = (h.get("relation"), h.get("disease"))
        if not all(key) or key in known:
            continue
        vault.add_family_history(vault_path, h["relation"], h["disease"],
                                 h.get("note", ""))
        known.add(key)
        history_added += 1

    aliases_added = 0
    if restore_names:
        for name, relation in (payload.get("aliases") or {}).items():
            config.add_alias(name, relation)
            aliases_added += 1

    return {"added": added, "skipped": skipped,
            "history_added": history_added, "aliases_added": aliases_added}


def import_family_file(vault_path: Path, path: Path,
                       restore_names: bool = False) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return import_family(vault_path, payload, restore_names)
