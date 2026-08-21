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
