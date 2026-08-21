"""추이 인사이트(series_insights·build_highlights) 테스트 — 순수 함수라 vault 불필요."""
import pytest

from health14 import analysis


def _series(metric, pairs):
    return {metric: [{"year": y, "value": v} for y, v in pairs]}


# ---------------------------------------------------------------- series_insights

def test_단일_시점은_인사이트_없음():
    out = analysis.series_insights(_series("체중", [(2025, 80)]))
    assert out == {}


def test_상승_추세는_악화():
    out = analysis.series_insights(
        _series("공복혈당", [(2022, 95), (2023, 105), (2024, 118)]))
    ins = out["공복혈당"]
    assert ins["direction"] == "악화"
    assert ins["change_since_first"] == 23
    assert ins["first_year"] == 2022 and ins["last_year"] == 2024


def test_하락_추세는_개선():
    out = analysis.series_insights(_series("체중", [(2022, 85), (2023, 82), (2024, 78)]))
    assert out["체중"]["direction"] == "개선"


def test_higher_is_better_는_방향_반전():
    # HDL 상승 = 개선, eGFR 하락 = 악화
    up = analysis.series_insights(_series("HDL", [(2022, 40), (2024, 55)]))
    assert up["HDL"]["direction"] == "개선"
    down = analysis.series_insights(_series("eGFR", [(2022, 95), (2024, 70)]))
    assert down["eGFR"]["direction"] == "악화"


def test_미세_변동은_유지():
    out = analysis.series_insights(_series("체중", [(2022, 80.0), (2023, 80.2), (2024, 80.1)]))
    assert out["체중"]["direction"] == "유지"


def test_best_worst_연도():
    out = analysis.series_insights(
        _series("체중", [(2022, 85), (2023, 78), (2024, 81)]))
    ins = out["체중"]
    assert ins["best"] == {"year": 2023, "value": 78}
    assert ins["worst"] == {"year": 2022, "value": 85}


def test_best_worst_higher_is_better_반전():
    out = analysis.series_insights(_series("HDL", [(2022, 42), (2023, 58), (2024, 50)]))
    assert out["HDL"]["best"]["year"] == 2023
    assert out["HDL"]["worst"]["year"] == 2022


def test_연속_악화_스트릭():
    out = analysis.series_insights(
        _series("수축기혈압", [(2021, 118), (2022, 124), (2023, 131), (2024, 139)]))
    assert out["수축기혈압"]["streak"] == {"kind": "악화", "count": 3}


def test_스트릭은_마지막_전환점에서_끊김():
    out = analysis.series_insights(
        _series("체중", [(2021, 80), (2022, 84), (2023, 82), (2024, 79)]))
    assert out["체중"]["streak"] == {"kind": "개선", "count": 2}


def test_판정_변화_기록():
    # 공복혈당 95(정상) → 118(주의 구간)
    out = analysis.series_insights(_series("공복혈당", [(2022, 95), (2024, 118)]))
    assert out["공복혈당"]["status_change"] == "정상→주의"
    same = analysis.series_insights(_series("공복혈당", [(2022, 90), (2024, 95)]))
    assert same["공복혈당"]["status_change"] is None


def test_연도_없는_포인트도_동작():
    out = analysis.series_insights(
        {"체중": [{"year": None, "value": 84}, {"year": None, "value": 80}]})
    assert out["체중"]["direction"] == "개선"


# ---------------------------------------------------------------- build_highlights

def test_판정_악화는_경고_하이라이트():
    ins = analysis.series_insights(_series("공복혈당", [(2022, 95), (2024, 130)]))
    hl = analysis.build_highlights(ins, {})
    kinds = [h["kind"] for h in hl]
    assert "entered_risk" in kinds
    h = next(h for h in hl if h["kind"] == "entered_risk")
    assert h["severity"] == 2 and "공복혈당" in h["text"]


def test_판정_개선은_긍정_하이라이트():
    ins = analysis.series_insights(_series("공복혈당", [(2022, 118), (2024, 95)]))
    hl = analysis.build_highlights(ins, {})
    assert any(h["kind"] == "returned_normal" and h["severity"] == 0 for h in hl)


def test_연속_악화_스트릭_하이라이트():
    ins = analysis.series_insights(
        _series("체중", [(2021, 78), (2022, 81), (2023, 84), (2024, 87)]))
    hl = analysis.build_highlights(ins, {})
    assert any(h["kind"] == "streak_worse" and "3회 연속" in h["text"] for h in hl)


def test_개선_스트릭이_최고기록이면_문구_포함():
    ins = analysis.series_insights(
        _series("체중", [(2021, 88), (2022, 84), (2023, 81), (2024, 78)]))
    hl = analysis.build_highlights(ins, {})
    h = next(h for h in hl if h["kind"] == "streak_better")
    assert "기록상 최고" in h["text"]


def test_심각한_하이라이트가_앞에_온다():
    series = {}
    series.update(_series("체중", [(2021, 88), (2022, 84), (2023, 81), (2024, 78)]))
    series.update(_series("공복혈당", [(2021, 95), (2022, 105), (2023, 115), (2024, 130)]))
    ins = analysis.series_insights(series)
    hl = analysis.build_highlights(ins, {})
    assert hl[0]["severity"] == 2


def test_변화_없으면_하이라이트_없음():
    ins = analysis.series_insights(_series("체중", [(2022, 80.0), (2024, 80.05)]))
    assert analysis.build_highlights(ins, {}) == []


# ---------------------------------------------------------------- build_summary

import re

RISK = {"metric": "수축기혈압", "value": 165, "unit": "mmHg", "status": "위험",
        "label": "높음", "trend": "악화", "family_history": False}
CAUTION = {"metric": "공복혈당", "value": 110, "unit": "mg/dL", "status": "주의",
           "label": "경계", "trend": "", "family_history": False}
DEPT = {"tag": "혈압", "dept": "순환기내과", "status": "위험", "cadence": "즉시 진료 권장"}
IMP = {"metric": "체중", "kind": "streak_better", "severity": 0,
       "text": "체중 2회 연속 개선"}


def test_summary_top_risk_와_action():
    s = analysis.build_summary(45, [RISK], [DEPT], {}, [])
    assert s["top_risk"]["metric"] == "수축기혈압"
    assert "순환기내과" in s["top_risk"]["action"]
    assert s["top_action"] == "순환기내과 방문 — 즉시 진료 권장"


def test_summary_개선만_있는_경우():
    s = analysis.build_summary(45, [], [], {}, [IMP])
    assert s["top_risk"] is None
    assert s["top_improvement"]["metric"] == "체중"
    assert s["masked"] == "위험 0건 · 주의 0건 · 개선 1건"


def test_summary_모두_정상():
    s = analysis.build_summary(45, [], [], {}, [])
    assert s["top_risk"] is None and s["top_improvement"] is None
    assert s["masked"] == "특이사항 없음"
    assert "정상 범위" in s["sentences"][0]


def test_summary_opinion_문장_호환():
    s = analysis.build_summary(45, [RISK, CAUTION], [DEPT], {"체중": "악화"}, [])
    joined = " ".join(s["sentences"])
    assert "위험 범위" in joined and "주의 범위" in joined and "악화 추세" in joined


def test_masked_에_수치나_항목명이_없다():
    """외부 전송 안전성 핀 — masked 는 건수 요약만 담는다."""
    s = analysis.build_summary(45, [RISK, CAUTION], [DEPT], {}, [IMP])
    assert re.fullmatch(r"[가-힣 0-9건·]+", s["masked"])
    for word in ("수축기혈압", "공복혈당", "체중", "165", "110", "mmHg"):
        assert word not in s["masked"]


# ---------------------------------------------------------------- family_matrix

def _member(relation, tag_status):
    return {"relation": relation, "display": relation, "tag_status": tag_status}


def test_matrix_행과_태그():
    fm = analysis.family_matrix([
        _member("나", {"혈압": "주의"}),
        _member("부인", {"혈당": "위험"}),
    ])
    assert "혈압" in fm["tags"] and "혈당" in fm["tags"]
    row = next(r for r in fm["rows"] if r["relation"] == "나")
    assert row["status"]["혈압"] == "주의"
    assert row["status"]["혈당"] == "-"  # 미측정


def test_공통_위험은_2명_이상():
    fm = analysis.family_matrix([
        _member("나", {"혈압": "주의"}),
        _member("부인", {"혈압": "위험"}),
        _member("아들", {}),
    ])
    assert fm["common"][0]["tag"] == "혈압"
    assert fm["common"][0]["count"] == 2
    assert fm["headline"] == "가족 공통 위험: 혈압 (2명)"


def test_한_명만_위험이면_공통_아님():
    fm = analysis.family_matrix([
        _member("나", {"혈압": "위험"}),
        _member("부인", {}),
    ])
    assert fm["common"] == [] and fm["headline"] is None


def test_관찰은_공통_위험에_포함되지_않음():
    fm = analysis.family_matrix([
        _member("나", {"혈당": "관찰"}),
        _member("부인", {"혈당": "관찰"}),
    ])
    assert fm["common"] == []


# ---------------------------------------------------------------- checkup_compliance

import datetime as _dt

REC_GENERAL = {"name": "일반건강검진", "interval_years": 2,
               "evidence_metrics": ["수축기혈압", "공복혈당"]}
REC_ENDO = {"name": "위내시경(위암검진)", "interval_years": 2, "evidence_metrics": []}


def test_혈액검사류는_수치_존재로_이행_판정():
    checkups = [{"year": 2024, "metrics": {"공복혈당": 95}}]
    comp = analysis.checkup_compliance([REC_GENERAL], checkups, _dt.date(2025, 6, 1))
    item = comp["items"][0]
    assert item["last_year"] == 2024 and item["due_year"] == 2026
    assert item["status"] == "이행"


def test_기한_도래_경계():
    checkups = [{"year": 2024, "metrics": {"공복혈당": 95}}]
    comp = analysis.checkup_compliance([REC_GENERAL], checkups, _dt.date(2026, 3, 1))
    assert comp["items"][0]["status"] == "기한 도래"
    assert comp["items"][0]["dday"] == 0


def test_지연_판정과_overdue_목록():
    checkups = [{"year": 2020, "metrics": {"공복혈당": 95}}]
    comp = analysis.checkup_compliance([REC_GENERAL], checkups, _dt.date(2026, 1, 1))
    item = comp["items"][0]
    assert item["status"] == "지연" and item["dday"] == -4
    assert comp["overdue"] == [item]


def test_기록_없으면_분모에서_제외():
    comp = analysis.checkup_compliance([REC_GENERAL, REC_ENDO], [], _dt.date(2026, 1, 1))
    assert all(i["status"] == "기록 없음" for i in comp["items"])
    assert comp["rate"] is None
    assert comp["overdue"] == []


def test_이행률은_기록있는_항목만_분모():
    checkups = [{"year": 2024, "metrics": {"공복혈당": 95}}]  # 일반건강검진만 기록
    comp = analysis.checkup_compliance([REC_GENERAL, REC_ENDO], checkups, _dt.date(2025, 1, 1))
    # 일반건강검진=이행, 위내시경=기록없음(분모 제외) → 이행률 100%
    assert comp["rate"] == 100


def test_exams_리스트로_비혈액검사_매칭():
    checkups = [{"year": 2023, "metrics": {}, "exams": ["위내시경"]}]
    comp = analysis.checkup_compliance([REC_ENDO], checkups, _dt.date(2026, 1, 1))
    item = comp["items"][0]
    assert item["last_year"] == 2023 and item["status"] == "지연"


def test_가족력_단축_주기가_그대로_반영():
    rec = {"name": "위내시경(위암검진)", "interval_years": 1, "evidence_metrics": []}
    checkups = [{"year": 2025, "metrics": {}, "exams": ["위내시경"]}]
    comp = analysis.checkup_compliance([rec], checkups, _dt.date(2026, 6, 1))
    assert comp["items"][0]["due_year"] == 2026
    assert comp["items"][0]["status"] == "기한 도래"


def test_최근_기록을_우선한다():
    checkups = [
        {"year": 2020, "metrics": {}, "exams": ["위내시경"]},
        {"year": 2024, "metrics": {}, "exams": ["위내시경"]},
    ]
    comp = analysis.checkup_compliance([REC_ENDO], checkups, _dt.date(2025, 1, 1))
    assert comp["items"][0]["last_year"] == 2024


# ---------------------------------------------------------------- vault.add_checkup exams

from health14 import vault as _vault_mod


def test_add_checkup_exams_누적_중복제거(tmp_path):
    v = tmp_path / "vault"
    _vault_mod.init_vault(v)
    _vault_mod.add_member(v, "나", 1980, "M")
    _vault_mod.add_checkup(v, "나", 2025, {"체중": 75}, exams=["위내시경", "대장내시경"])
    _vault_mod.add_checkup(v, "나", 2025, {}, exams=["위내시경", "유방촬영"])
    checkups = _vault_mod.load_checkups(v, "나")
    assert checkups[0]["exams"] == ["위내시경", "대장내시경", "유방촬영"]


# ---------------------------------------------------------------- vault profile

def test_load_profile_없으면_빈딕셔너리(tmp_path):
    v = tmp_path / "vault"
    _vault_mod.init_vault(v)
    _vault_mod.add_member(v, "나", 1980, "M")
    prof = _vault_mod.load_profile(v, "나")
    # add_member 가 프로필.md 를 만들어두므로 conditions/medications 키는 있다
    assert prof.get("smoking") is None and prof.get("bp_treated") is None


def test_update_profile_라운드트립(tmp_path):
    v = tmp_path / "vault"
    _vault_mod.init_vault(v)
    _vault_mod.add_member(v, "나", 1980, "M")
    _vault_mod.update_profile(v, "나", {"smoking": True, "bp_treated": False})
    prof = _vault_mod.load_profile(v, "나")
    assert prof["smoking"] is True and prof["bp_treated"] is False


def test_update_profile_None값은_건드리지_않는다(tmp_path):
    v = tmp_path / "vault"
    _vault_mod.init_vault(v)
    _vault_mod.add_member(v, "나", 1980, "M")
    _vault_mod.update_profile(v, "나", {"smoking": True})
    _vault_mod.update_profile(v, "나", {"smoking": None, "bp_treated": True})
    prof = _vault_mod.load_profile(v, "나")
    assert prof["smoking"] is True and prof["bp_treated"] is True


def test_update_profile_미등록_구성원은_거부(tmp_path):
    v = tmp_path / "vault"
    _vault_mod.init_vault(v)
    with pytest.raises(SystemExit):
        _vault_mod.update_profile(v, "나", {"smoking": True})


# ---------------------------------------------------------------- cvd glue in build_member_report

def test_report_는_cvd_필드를_포함(tmp_path):
    from health14 import analysis as _analysis
    v = tmp_path / "vault"
    _vault_mod.init_vault(v)
    _vault_mod.add_member(v, "나", 1970, "M")
    _vault_mod.add_checkup(v, "나", 2025, {
        "수축기혈압": 140, "총콜레스테롤": 213, "HDL": 50})
    report = _analysis.build_member_report(v, "나", today=_dt.date(2025, 6, 1))
    assert report["cvd"] is not None
    assert report["cvd"]["risk_pct"] is not None
    assert "profile" in report and report["profile"]["smoking"] is None


def test_report_cvd에_whatif가_붙는다(tmp_path):
    from health14 import analysis as _analysis
    v = tmp_path / "vault"
    _vault_mod.init_vault(v)
    _vault_mod.add_member(v, "나", 1970, "M")
    _vault_mod.update_profile(v, "나", {"smoking": True})
    _vault_mod.add_checkup(v, "나", 2025, {
        "수축기혈압": 140, "총콜레스테롤": 213, "HDL": 50})
    report = _analysis.build_member_report(v, "나", today=_dt.date(2025, 6, 1))
    assert "whatif" in report["cvd"]
    assert any(w["factor"] == "흡연 중단" for w in report["cvd"]["whatif"])


def test_수치_부족하면_cvd_는_None(tmp_path):
    from health14 import analysis as _analysis
    v = tmp_path / "vault"
    _vault_mod.init_vault(v)
    _vault_mod.add_member(v, "나", 1970, "M")
    _vault_mod.add_checkup(v, "나", 2025, {"체중": 75})
    report = _analysis.build_member_report(v, "나", today=_dt.date(2025, 6, 1))
    assert report["cvd"] is None
