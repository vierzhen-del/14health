"""캘린더용 경량 기록 인덱스.

검진·진료·분석 노트의 frontmatter만 읽어 (날짜 · 구성원 · 종류 · 제목)만
뽑는다. 본문·수치는 읽지 않으므로 노트가 수천 개여도 빠르다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

from health14 import relations, vault

KIND_LABEL = {"checkup": "검진", "visit": "진료", "analysis": "분석"}


def _iso_week(date: dt.date) -> str:
    year, week, _ = date.isocalendar()
    return f"{year}-W{week:02d}"


def _parse_date(value: Any) -> Optional[dt.date]:
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def build_index(vault_path: Path, year: Optional[int] = None) -> List[Dict[str, Any]]:
    """vault 전체 기록 인덱스 (날짜 오름차순).

    각 항목: {date, week, month, relation, display, kind, label, title, note}
    year를 주면 그 해 기록만.
    """
    members = vault.load_members(vault_path)
    display = {m["relation"]: relations.display_name(m) for m in members}

    entries: List[Dict[str, Any]] = []
    for m in members:
        relation = m["relation"]
        base = vault_path / vault.MEMBERS_DIR / relation
        for folder, kind in (("검진", "checkup"), ("진료", "visit"),
                             ("분석", "analysis")):
            d = base / folder
            if not d.exists():
                continue
            for f in sorted(d.glob("*.md")):
                meta, _ = vault.read_note(f)
                date = _parse_date(meta.get("date"))
                if date is None and meta.get("year"):
                    date = dt.date(int(meta["year"]), 1, 1)
                if date is None:
                    continue
                if year and date.year != year:
                    continue
                entries.append({
                    "date": date.isoformat(),
                    "week": _iso_week(date),
                    "month": date.month,
                    "year": date.year,
                    "relation": relation,
                    "display": display.get(relation, relation),
                    "kind": kind,
                    "label": KIND_LABEL.get(kind, kind),
                    "title": _title_for(kind, meta, f),
                    "note": f.relative_to(vault_path).as_posix(),
                })
    entries.sort(key=lambda e: (e["date"], e["display"]))
    return entries


def _title_for(kind: str, meta: Dict[str, Any], path: Path) -> str:
    if kind == "checkup":
        return f"{meta.get('year', '')} 건강검진".strip()
    if kind == "visit":
        hospital = meta.get("hospital") or "진료"
        diagnosis = (meta.get("diagnosis") or "").split(".")[0].strip()
        return f"{hospital} — {diagnosis}" if diagnosis else hospital
    if kind == "analysis":
        return "위험도 분석"
    return path.stem


def available_years(entries: List[Dict[str, Any]]) -> List[int]:
    return sorted({e["year"] for e in entries}, reverse=True)
