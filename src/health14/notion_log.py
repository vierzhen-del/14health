"""노션 이력 동기화 — 마스킹된 화이트리스트 필드만 전송.

노션에는 절대 건강 수치·증상·처방·실명을 보내지 않는다.
전송 페이로드는 build_payload()의 화이트리스트 5개 필드로만 구성되어
구조적으로 다른 데이터가 나갈 수 없다. 제목은 추가로 정규식 마스킹을 거친다.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from health14 import anonymize, config, vault

NOTION_API = "https://api.notion.com/v1/pages"
NOTION_VERSION = "2022-06-28"

# 노션 "14health 이력" DB의 select 옵션과 일치
KNOWN_TARGETS = {"나", "부인", "아들", "딸", "어머니", "아버지"}
KNOWN_ACTIONS = {"검진입력", "진료입력", "가족력입력", "위험분석",
                 "대시보드생성", "공유이미지", "내보내기", "가져오기"}


def build_payload(database_id: str, entry: Dict[str, str],
                  vault_path: Path) -> Dict[str, Any]:
    """이력 한 줄 → 노션 페이지 페이로드 (화이트리스트 필드만).

    entry: vault.load_log() 의 행 {date, target, action, title, note}
    """
    title = anonymize.mask_for_external(entry.get("title", ""))
    target = entry.get("target", "기타")
    if target not in KNOWN_TARGETS:
        target = "기타"
    action = entry.get("action", "")
    properties: Dict[str, Any] = {
        "제목": {"title": [{"text": {"content": title or "(제목 없음)"}}]},
        "날짜": {"date": {"start": entry["date"]}},
        "대상": {"select": {"name": target}},
    }
    if action in KNOWN_ACTIONS:
        properties["작업유형"] = {"select": {"name": action}}
    note = entry.get("note", "")
    if note:
        properties["옵시디안링크"] = {"url": vault.obsidian_uri(vault_path, note)}
    return {"parent": {"database_id": database_id}, "properties": properties}


def sync(vault_path: Path, since: Optional[str] = None) -> int:
    """로컬 이력을 노션 DB로 동기화. 동기화된 행 수 반환."""
    cfg = config.load_config()
    token = cfg.get("notion_token")
    database_id = cfg.get("notion_database_id")
    if not token or not database_id:
        raise SystemExit(
            "노션 동기화가 설정되지 않았습니다. 로컬 이력만 유지됩니다.\n"
            "설정 방법:\n"
            "  14health config set notion_token <integration 토큰>\n"
            "  14health config set notion_database_id <이력 DB ID>\n"
            "(노션에서 내부 integration을 만들어 '14health 이력' DB에 연결하세요)")

    entries = vault.load_log(vault_path)
    # 이미 동기화한 행 수 이후의 행만 전송 (이력은 append-only)
    synced = int(cfg.get("notion_synced_count") or 0)
    if since:
        new_entries = [e for e in entries if e["date"] >= since]
    else:
        new_entries = entries[synced:]

    count = 0
    for entry in new_entries:
        payload = build_payload(database_id, entry, vault_path)
        req = urllib.request.Request(
            NOTION_API,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            resp.read()
        count += 1

    if not since:
        cfg["notion_synced_count"] = synced + count
        config.save_config(cfg)
    return count
