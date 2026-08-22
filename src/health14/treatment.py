"""현재 진료내역 — 치료중 질환 · 복약중인 약 · 다음 예약.

진료 노트(`구성원/<관계>/진료/<날짜>-<병원>.md`)는 날짜로 키가 잡힌 **불변
이벤트**라 갱신 경로가 없다. 반면 "지금 치료 중"은 계속 바뀌는 **구성원 단위
상태**이므로 `구성원/<관계>/프로필.md` frontmatter 에 둔다 — `vault.update_profile`
이 원자적 쓰기와 리스트 통째 교체(= 약 끊음 표현)를 이미 보장한다.

**병원 실명·증권번호류는 스키마에 없다.** 아래 화이트리스트 밖의 키는 버려지므로
실수로도 저장되지 않는다. 담당 병원은 실명이 아니라 진료과 종류(`dept`)로만 적는다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

from health14 import anonymize, vault

# 저장 허용 필드 — 이 목록 밖은 기록하지 않는다
CONDITION_FIELDS = ("name", "since", "status", "dept")
MED_FIELDS = ("name", "dose", "since", "for")
NEXT_VISIT_FIELDS = ("date", "dept", "purpose")

# 치료 상태 — "완치"는 현재 치료중 목록에서 빠진다
CONDITION_STATES = ["관리중", "치료중", "추적관찰", "완치"]
ACTIVE_STATES = ("관리중", "치료중", "추적관찰")


def _clean(raw: Any, fields: tuple, name_key: str = "name") -> Optional[Dict[str, Any]]:
    """허용 필드만 남긴 dict 로 정규화. 문자열이면 name_key 로 승격(하위호환)."""
    if isinstance(raw, str):
        text = raw.strip()
        return {name_key: anonymize.anonymize(text)} if text else None
    if not isinstance(raw, dict):
        return None
    out: Dict[str, Any] = {}
    for key in fields:
        value = raw.get(key)
        if value in (None, "", []):
            continue
        out[key] = anonymize.anonymize(str(value).strip())
    return out or None


def normalize_conditions(raw: Any) -> List[Dict[str, Any]]:
    """치료중 질환 목록 정규화.

    기존 프로필의 `conditions: [당뇨]` 같은 **문자열 목록도 그대로 받는다**
    (riskscore 가 오래 전부터 읽던 형태 — 깨뜨리지 않는다).
    """
    items = raw if isinstance(raw, list) else ([raw] if raw else [])
    out = []
    for item in items:
        rec = _clean(item, CONDITION_FIELDS)
        if rec and rec.get("name"):
            if rec.get("status") and rec["status"] not in CONDITION_STATES:
                rec["status"] = "관리중"
            out.append(rec)
    return out


def normalize_medications(raw: Any) -> List[Dict[str, Any]]:
    items = raw if isinstance(raw, list) else ([raw] if raw else [])
    out = []
    for item in items:
        rec = _clean(item, MED_FIELDS)
        if rec and rec.get("name"):
            out.append(rec)
    return out


def normalize_next_visits(raw: Any) -> List[Dict[str, Any]]:
    items = raw if isinstance(raw, list) else ([raw] if raw else [])
    out = []
    for item in items:
        rec = _clean(item, NEXT_VISIT_FIELDS, name_key="date")
        if rec and rec.get("date"):
            out.append(rec)
    out.sort(key=lambda r: str(r["date"]))
    return out


def condition_names(profile: Dict[str, Any]) -> List[str]:
    """치료중 질환 이름 목록 — 문자열/dict 어느 형태로 저장돼 있든 동작한다."""
    return [c["name"] for c in normalize_conditions(profile.get("conditions"))]


def load_treatment(vault_path: Path, relation: str) -> Dict[str, List[Dict[str, Any]]]:
    """구성원의 현재 진료내역 (정규화 완료본)."""
    profile = vault.load_profile(vault_path, relation)
    return {
        "conditions": normalize_conditions(profile.get("conditions")),
        "medications": normalize_medications(profile.get("medications")),
        "next_visits": normalize_next_visits(profile.get("next_visits")),
    }


def active_conditions(treatment: Dict[str, Any]) -> List[Dict[str, Any]]:
    """완치를 제외한 현재 진행중인 질환."""
    return [c for c in treatment.get("conditions") or []
            if c.get("status", "관리중") in ACTIVE_STATES]


def set_treatment(vault_path: Path, relation: str,
                  conditions: Optional[List[Any]] = None,
                  medications: Optional[List[Any]] = None,
                  next_visits: Optional[List[Any]] = None) -> Path:
    """현재 진료내역 저장 — 넘긴 목록은 통째로 교체된다(항목 제거도 이 방식)."""
    fields: Dict[str, Any] = {}
    if conditions is not None:
        fields["conditions"] = normalize_conditions(conditions)
    if medications is not None:
        fields["medications"] = normalize_medications(medications)
    if next_visits is not None:
        fields["next_visits"] = normalize_next_visits(next_visits)
    if not fields:
        raise SystemExit("변경할 항목이 없습니다.")
    return vault.update_profile(vault_path, relation, fields)


def add_item(vault_path: Path, relation: str, kind: str, item: Dict[str, Any]) -> Path:
    """항목 하나 추가 (같은 이름이 있으면 교체)."""
    current = load_treatment(vault_path, relation)
    key = {"condition": "conditions", "medication": "medications",
           "next_visit": "next_visits"}.get(kind)
    if key is None:
        raise SystemExit(f"알 수 없는 종류입니다: {kind}")
    normalizer = {"conditions": normalize_conditions,
                  "medications": normalize_medications,
                  "next_visits": normalize_next_visits}[key]
    new = normalizer([item])
    if not new:
        raise SystemExit("내용이 비어 있습니다.")
    ident = "date" if key == "next_visits" else "name"
    rest = [x for x in current[key] if x.get(ident) != new[0].get(ident)]
    return set_treatment(vault_path, relation, **{key: rest + new})


def end_item(vault_path: Path, relation: str, kind: str, name: str) -> Path:
    """항목 종료 — 질환은 '완치'로 바꾸고, 약·예약은 목록에서 제거한다."""
    current = load_treatment(vault_path, relation)
    if kind == "condition":
        found = False
        for c in current["conditions"]:
            if c.get("name") == name:
                c["status"] = "완치"
                found = True
        if not found:
            raise SystemExit(f"치료중 질환에 없습니다: {name}")
        return set_treatment(vault_path, relation, conditions=current["conditions"])
    key = {"medication": "medications", "next_visit": "next_visits"}.get(kind)
    if key is None:
        raise SystemExit(f"알 수 없는 종류입니다: {kind}")
    ident = "date" if key == "next_visits" else "name"
    rest = [x for x in current[key] if x.get(ident) != name]
    if len(rest) == len(current[key]):
        raise SystemExit(f"목록에 없습니다: {name}")
    return set_treatment(vault_path, relation, **{key: rest})


# ---------------------------------------------------------------- 예약 조회

def upcoming_visits(vault_path: Path,
                    today: Optional[dt.date] = None) -> List[Dict[str, Any]]:
    """가족 전체의 다가오는 예약 — D-day 오름차순. 지난 예약은 제외한다."""
    today = today or dt.date.today()
    rows: List[Dict[str, Any]] = []
    for member in vault.load_members(vault_path):
        relation = member["relation"]
        for visit in load_treatment(vault_path, relation)["next_visits"]:
            try:
                date = dt.date.fromisoformat(str(visit["date"])[:10])
            except ValueError:
                continue
            days_left = (date - today).days
            if days_left < 0:
                continue
            rows.append({
                "relation": relation,
                "display": member.get("display") or relation,
                "date": date.isoformat(),
                "dept": visit.get("dept", ""),
                "purpose": visit.get("purpose", ""),
                "days_left": days_left,
                "soon": days_left <= 7,
            })
    rows.sort(key=lambda r: r["days_left"])
    return rows


def upcoming_summary(vault_path: Path,
                     today: Optional[dt.date] = None) -> Dict[str, Any]:
    """홈 배너용 요약 — 건수·가장 가까운 예약."""
    rows = upcoming_visits(vault_path, today)
    return {
        "count": len(rows),
        "next_date": rows[0]["date"] if rows else None,
        "soon": sum(1 for r in rows if r["soon"]),
    }
