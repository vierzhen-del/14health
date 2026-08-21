"""심혈관(관상동맥질환) 10년 위험도 — Framingham 포인트표 (오프라인 규칙 기반).

출처는 `data/guidelines/cvd_risk.yaml` 의 meta 를 참조. 이 모듈은 vault를
직접 읽지 않는 순수 함수만 담는다 — 입력은 analysis.py 가 조립해서 넘긴다.
"""
from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any, Dict, List, Optional

import yaml


@lru_cache(maxsize=None)
def _load() -> Dict[str, Any]:
    ref = resources.files("health14").joinpath("data/guidelines/cvd_risk.yaml")
    with ref.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _pick(bands: List[Dict[str, Any]], value: float) -> Dict[str, Any]:
    for b in bands:
        if "up_to" not in b or value < b["up_to"]:
            return b
    return bands[-1]


def _age_group(data: Dict[str, Any], age: int) -> str:
    return _pick(data["age_groups"], age)["key"]


def _points(data: Dict[str, Any], sex: str, age: int, total_chol: float,
           hdl: float, sbp: float, bp_treated: bool, smoking: bool) -> int:
    m = data["models"][sex]
    ag = _age_group(data, age)
    pts = _pick(m["age"], age)["pts"]
    pts += _pick(m["chol_by_age"][ag], total_chol)["pts"]
    pts += _pick(m["hdl"], hdl)["pts"]
    sbp_bands = m["sbp_treated"] if bp_treated else m["sbp_untreated"]
    pts += _pick(sbp_bands, sbp)["pts"]
    if smoking:
        pts += m["smoker_by_age"][ag]
    return pts


def _risk_for_points(data: Dict[str, Any], sex: str, points: int):
    band = _pick(data["models"][sex]["risk"], points)
    return band["pct"], band["label"]


def _heart_age(data: Dict[str, Any], sex: str, risk_pct: float) -> int:
    """참조군(비흡연·최적 수치) 나이 중 이 위험도에 처음 도달하는 나이.

    같은 위험도를 갖는, 위험요인이 모두 정상 범위인 사람의 나이 — 공식
    발표된 별도 표가 아니라 이미 검증된 연령·위험% 표에서 계산한다.
    """
    age_bands = data["models"][sex]["age"]
    ranges = data["age_band_ranges"]
    for ab, rng in zip(age_bands, ranges):
        pct, _ = _risk_for_points(data, sex, ab["pts"])
        if pct >= risk_pct:
            return rng["min"]
    return ranges[-1]["max"]


def cvd_inputs(age: int, sex: str, latest: Dict[str, Dict[str, Any]],
              profile: Dict[str, Any]) -> Dict[str, Any]:
    """검진 최근수치 + 프로필에서 위험점수 계산 입력을 조립.

    결측 항목은 assumptions(가정)·missing(계산 불가 사유)에 각각 기록한다.
    당뇨는 새 숫자 기준 없이 기존 classify() 판정(공복혈당·당화혈색소 위험)
    또는 프로필 conditions 로만 추정한다.
    """
    assumptions: List[str] = []
    missing: List[str] = []

    def _val(metric: str) -> Optional[float]:
        return (latest.get(metric) or {}).get("value")

    sbp = _val("수축기혈압")
    if sbp is None:
        missing.append("수축기혈압")
    total_chol = _val("총콜레스테롤")
    if total_chol is None:
        missing.append("총콜레스테롤")
    hdl = _val("HDL")
    if hdl is None:
        missing.append("HDL")

    smoking = profile.get("smoking")
    if smoking is None:
        assumptions.append("흡연 여부 미등록 — 비흡연으로 가정")
        smoking = False
    bp_treated = profile.get("bp_treated")
    if bp_treated is None:
        assumptions.append("혈압약 복용 여부 미등록 — 미복용으로 가정")
        bp_treated = False

    fg_status = (latest.get("공복혈당") or {}).get("status")
    a1c_status = (latest.get("당화혈색소") or {}).get("status")
    diabetes = (fg_status == "위험" or a1c_status == "위험"
               or "당뇨" in (profile.get("conditions") or []))

    return {
        "age": age, "sex": sex, "sbp": sbp, "total_chol": total_chol,
        "hdl": hdl, "smoking": bool(smoking), "bp_treated": bool(bp_treated),
        "diabetes": diabetes, "assumptions": assumptions, "missing": missing,
    }


def cvd_score(inputs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """위험점수 계산. 연령 범위 밖·성별 미상·필수 수치 결측이면 None."""
    data = _load()
    meta = data["meta"]
    age, sex = inputs["age"], inputs["sex"]
    if sex not in ("M", "F"):
        return None
    if not (meta["age_min"] <= age <= meta["age_max"]):
        return None
    if inputs["missing"] or inputs["sbp"] is None or inputs["total_chol"] is None \
            or inputs["hdl"] is None:
        return None

    if inputs["diabetes"]:
        return {
            "diabetes_equivalent": True,
            "points": None, "risk_pct": None, "risk_label": None,
            "band": "매우 높음", "heart_age": None, "heart_age_gap": None,
            "normal_risk_pct": None, "relative": None,
            "assumptions": inputs["assumptions"], "missing": [],
            "note": meta["diabetes_note"], "disclaimer": meta["disclaimer"],
        }

    points = _points(data, sex, age, inputs["total_chol"], inputs["hdl"],
                     inputs["sbp"], inputs["bp_treated"], inputs["smoking"])
    risk_pct, risk_label = _risk_for_points(data, sex, points)
    band = _pick(data["bands"], risk_pct)["label"]

    normal_points = _pick(data["models"][sex]["age"], age)["pts"]
    normal_risk_pct, _ = _risk_for_points(data, sex, normal_points)

    heart_age = _heart_age(data, sex, risk_pct)
    heart_age_gap = heart_age - age

    relative = 1.0 if risk_pct <= normal_risk_pct else round(risk_pct / normal_risk_pct, 1)

    return {
        "diabetes_equivalent": False,
        "points": points, "risk_pct": risk_pct, "risk_label": risk_label,
        "band": band, "heart_age": heart_age, "heart_age_gap": heart_age_gap,
        "normal_risk_pct": normal_risk_pct, "relative": relative,
        "assumptions": inputs["assumptions"], "missing": [],
        "note": None, "disclaimer": meta["disclaimer"],
    }
