"""가이드라인 기반 판정·추천 엔진 (오프라인 규칙 기반).

- classify(): 수치 → 정상/주의/위험 판정
- recommended_checkups(): 연령·성별·가족력 → 권장 검진항목·주기
- lifestyle_advice(): 연령대 + 위험 태그 → 생활습관 권고
- quarterly_plan(): 향후 1년 분기별(Q1~Q4) 검진 계획
"""
from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any, Dict, List, Optional, Tuple

import yaml


@lru_cache(maxsize=None)
def _load(name: str) -> Dict[str, Any]:
    ref = resources.files("health14").joinpath(f"data/guidelines/{name}.yaml")
    with ref.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def reference_ranges() -> Dict[str, Any]:
    return _load("reference_ranges")


def schedule() -> Dict[str, Any]:
    return _load("checkup_schedule")


def lifestyle() -> Dict[str, Any]:
    return _load("lifestyle")


# ---------------------------------------------------------------- 수치 판정

def metric_def(metric: str, sex: str = "") -> Optional[Dict[str, Any]]:
    metrics = reference_ranges()["metrics"]
    if metric == "허리둘레":
        metric = "허리둘레여" if sex == "F" else "허리둘레남"
    return metrics.get(metric)


def classify(metric: str, value: float, sex: str = "") -> Optional[Dict[str, str]]:
    """수치 판정 → {status, label, tag, unit} (기준 없는 항목은 None)."""
    mdef = metric_def(metric, sex)
    if mdef is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    for band in mdef["bands"]:
        if "up_to" not in band or v < float(band["up_to"]):
            return {
                "status": band["status"],
                "label": band.get("label", band["status"]),
                "tag": mdef.get("tag", ""),
                "unit": mdef.get("unit", ""),
            }
    return None


STATUS_ORDER = {"정상": 0, "주의": 1, "위험": 2}


# ---------------------------------------------------------------- 검진 추천

def recommended_checkups(age: int, sex: str,
                         family_diseases: Optional[List[str]] = None,
                         include_high_risk: bool = False) -> List[Dict[str, Any]]:
    """연령·성별·가족력에 해당하는 권장 검진 목록."""
    family_diseases = family_diseases or []
    result = []
    for item in schedule()["checkups"]:
        if item.get("sex", "all") not in ("all", sex):
            continue
        fh = item.get("family_history")
        fh_hit = bool(fh) and any(d in family_diseases for d in fh.get("diseases", []))
        age_min = item.get("age_min", 0)
        age_max = item.get("age_max", 200)
        interval = item.get("interval_years", 1)
        note = item.get("detail", "")
        if fh_hit:
            age_min = fh.get("age_min", age_min)
            interval = fh.get("interval_years", interval)
            note = (fh.get("note") or f"가족력({', '.join(fh['diseases'])})으로 강화된 기준") + " · " + note
        if not (age_min <= age <= age_max):
            continue
        if item.get("high_risk_only") and not (include_high_risk or fh_hit):
            continue
        result.append({
            "name": item["name"],
            "interval_years": interval,
            "detail": note,
            "family_history": fh_hit,
        })
    return result


def lifecycle_stages() -> List[Dict[str, Any]]:
    return schedule()["lifecycle"]


def stage_of(age: int) -> Dict[str, Any]:
    for s in lifecycle_stages():
        if s["age_min"] <= age <= s["age_max"]:
            return s
    return lifecycle_stages()[-1]


# ---------------------------------------------------------------- 생활습관

def lifestyle_advice(age: int, risk_tags: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """{연령대 권고, 위험태그별 권고} 반환."""
    risk_tags = risk_tags or []
    base: List[str] = []
    for band in lifestyle()["age_bands"]:
        if band["age_min"] <= age <= band["age_max"]:
            base = list(band["advice"])
            break
    risk: List[str] = []
    risk_map = lifestyle()["risk_advice"]
    for tag in risk_tags:
        for adv in risk_map.get(tag, []):
            if adv not in risk:
                risk.append(adv)
    return {"age_band": base, "risk": risk}


# ---------------------------------------------------------------- 진료과 추천

def department_advice(tag_status: Dict[str, str]) -> List[Dict[str, str]]:
    """위험 태그별 최악 상태 → 권장 진료과·방문주기."""
    depts = reference_ranges()["departments"]
    result = []
    for tag, status in tag_status.items():
        if status == "정상" or tag not in depts:
            continue
        d = depts[tag]
        result.append({
            "tag": tag,
            "dept": d["dept"],
            "status": status,
            "cadence": d.get(status, ""),
        })
    result.sort(key=lambda r: -STATUS_ORDER.get(r["status"], 0))
    return result


def family_history_tags(family_diseases: List[str]) -> List[str]:
    """가족력 질환 → 관련 수치 태그."""
    mapping = reference_ranges().get("family_history_tags", {})
    tags = []
    for d in family_diseases:
        tag = mapping.get(d)
        if tag and tag not in tags:
            tags.append(tag)
    return tags


# ---------------------------------------------------------------- 연간 계획

def quarterly_plan(recs: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """권장 검진을 향후 1년 분기별로 배분 (참고 이미지 2 스타일)."""
    quarters: Dict[str, List[str]] = {"Q1": [], "Q2": [], "Q3": [], "Q4": []}
    # 접종류는 Q4(가을), 나머지는 순환 배분
    order = ["Q1", "Q2", "Q3"]
    i = 0
    for rec in recs:
        label = rec["name"]
        if rec["interval_years"] > 1:
            label += f" ({rec['interval_years']}년 주기)"
        if "접종" in rec["name"]:
            quarters["Q4"].append(label)
            continue
        quarters[order[i % len(order)]].append(label)
        i += 1
    return quarters
