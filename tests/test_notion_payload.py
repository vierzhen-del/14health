"""노션 페이로드에 수치·실명이 구조적으로 포함될 수 없음을 검증."""
import json

from health14 import notion_log

ALLOWED_PROPERTIES = {"제목", "날짜", "대상", "작업유형", "옵시디안링크"}


def _entry(**kw):
    base = {"date": "2026-07-11", "target": "나", "action": "검진입력",
            "title": "2025 건강검진 입력", "note": "[[구성원/나/검진/2025-건강검진]]"}
    base.update(kw)
    return base


def test_payload_whitelist_only(vault_path):
    payload = notion_log.build_payload("db-id", _entry(), vault_path)
    assert set(payload.keys()) == {"parent", "properties"}
    assert set(payload["properties"].keys()) <= ALLOWED_PROPERTIES


def test_payload_title_masked(vault_path):
    entry = _entry(title="혈압 138/88 mmHg 김영희 검진")
    payload = notion_log.build_payload("db-id", entry, vault_path)
    text = json.dumps(payload, ensure_ascii=False)
    assert "138" not in text and "88" not in text


def test_payload_unknown_target_becomes_other(vault_path):
    payload = notion_log.build_payload("db-id", _entry(target="김철수"), vault_path)
    assert payload["properties"]["대상"]["select"]["name"] == "기타"
    assert "김철수" not in json.dumps(payload, ensure_ascii=False)


def test_payload_obsidian_link(vault_path):
    payload = notion_log.build_payload("db-id", _entry(), vault_path)
    url = payload["properties"]["옵시디안링크"]["url"]
    assert url.startswith("obsidian://open?vault=")
