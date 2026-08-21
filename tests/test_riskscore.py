"""심혈관 위험점수(riskscore.py) 테스트 — 공개 포인트표 기반 순수 함수.

worked_example 은 data/guidelines/cvd_risk.yaml 의 meta.worked_example 과
동일해야 한다(코드 값 변경 시 yaml 도 같이 검토).
"""
import re

import pytest

from health14 import riskscore


def _inputs(**kw):
    base = {"age": 55, "sex": "M", "sbp": 140, "total_chol": 213, "hdl": 50,
            "smoking": False, "bp_treated": False, "diabetes": False,
            "assumptions": [], "missing": []}
    base.update(kw)
    return base


def test_worked_example_남성_12점_10퍼센트():
    """yaml meta.worked_example — 코드로 검증한 기준 벡터."""
    r = riskscore.cvd_score(_inputs())
    assert r["points"] == 12
    assert r["risk_pct"] == 10
    assert r["diabetes_equivalent"] is False


def test_연령_범위_밖은_None():
    assert riskscore.cvd_score(_inputs(age=19)) is None
    assert riskscore.cvd_score(_inputs(age=80)) is None


def test_성별_미상은_None():
    assert riskscore.cvd_score(_inputs(sex="")) is None


def test_필수_수치_결측이면_None():
    assert riskscore.cvd_score(_inputs(sbp=None)) is None
    assert riskscore.cvd_score(_inputs(total_chol=None)) is None
    assert riskscore.cvd_score(_inputs(hdl=None)) is None


def test_당뇨는_위험동등물로_별도_점수_없이_판정():
    r = riskscore.cvd_score(_inputs(diabetes=True))
    assert r["diabetes_equivalent"] is True
    assert r["points"] is None and r["risk_pct"] is None
    assert r["band"] == "매우 높음"
    assert "위험동등물" in r["note"]


def test_치료중_혈압이_미치료보다_점수_높음():
    untreated = riskscore.cvd_score(_inputs(bp_treated=False, sbp=125))
    treated = riskscore.cvd_score(_inputs(bp_treated=True, sbp=125))
    assert treated["points"] > untreated["points"]


def test_흡연은_연령대별_가산점():
    non_smoker = riskscore.cvd_score(_inputs(smoking=False))
    smoker = riskscore.cvd_score(_inputs(smoking=True))
    assert smoker["points"] == non_smoker["points"] + 3  # 50-59 남성 흡연 가산 3점


def test_여성_모델도_동작():
    r = riskscore.cvd_score(_inputs(sex="F", age=60, sbp=130, total_chol=220, hdl=55))
    assert r is not None and r["risk_pct"] is not None


def test_혈관나이는_실제_나이보다_위험할수록_높다():
    low = riskscore.cvd_score(_inputs(age=40, sbp=110, total_chol=150, hdl=65))
    high = riskscore.cvd_score(_inputs(age=40, sbp=175, total_chol=280, hdl=35, smoking=True))
    assert high["heart_age"] >= low["heart_age"]


def test_relative_는_1_이상():
    r = riskscore.cvd_score(_inputs())
    assert r["relative"] >= 1.0


def test_최적_수치는_relative_1에_가깝다():
    r = riskscore.cvd_score(_inputs(sbp=110, total_chol=150, hdl=65, smoking=False))
    assert r["relative"] == 1.0


def test_가정_기록_비흡연_비치료_디폴트():
    inputs = riskscore.cvd_inputs(
        age=55, sex="M",
        latest={"수축기혈압": {"value": 140}, "총콜레스테롤": {"value": 213},
               "HDL": {"value": 50}},
        profile={})
    assert inputs["smoking"] is False and inputs["bp_treated"] is False
    assert any("흡연" in a for a in inputs["assumptions"])
    assert any("혈압약" in a for a in inputs["assumptions"])


def test_당뇨_추정_공복혈당_위험():
    inputs = riskscore.cvd_inputs(
        age=55, sex="M",
        latest={"수축기혈압": {"value": 140}, "총콜레스테롤": {"value": 213},
               "HDL": {"value": 50}, "공복혈당": {"value": 135, "status": "위험"}},
        profile={})
    assert inputs["diabetes"] is True


def test_당뇨_추정_conditions_에서():
    inputs = riskscore.cvd_inputs(
        age=55, sex="M",
        latest={"수축기혈압": {"value": 140}, "총콜레스테롤": {"value": 213},
               "HDL": {"value": 50}},
        profile={"conditions": ["당뇨"]})
    assert inputs["diabetes"] is True


def test_결측_수치는_missing에_기록():
    inputs = riskscore.cvd_inputs(age=55, sex="M", latest={}, profile={})
    assert set(inputs["missing"]) == {"수축기혈압", "총콜레스테롤", "HDL"}
    assert riskscore.cvd_score(inputs) is None


def test_riskscore_모듈에_가이드라인_숫자_리터럴이_없다():
    """안전핀 — 기준 숫자는 cvd_risk.yaml 에만 있어야 한다.

    AST로 실제 코드의 숫자 상수만 본다(문자열·독스트링은 제외) — 인덱싱·
    반올림 자릿수 등에 쓰이는 0/1 만 허용한다.
    """
    import ast
    import inspect

    src = inspect.getsource(riskscore)
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            if node.value not in (0, 1):
                offenders.append(node.value)
    assert offenders == []
