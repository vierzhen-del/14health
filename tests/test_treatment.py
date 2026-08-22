"""현재 진료내역 — 치료중 질환 · 복약 · 다음 예약."""
import datetime as dt

import pytest

from health14 import recommend, riskscore, treatment, vault


@pytest.fixture
def v(tmp_path):
    path = tmp_path / "vault"
    vault.init_vault(path)
    vault.add_member(path, "나", 1970, "M")
    return path


# ---------------------------------------------------------------- 정규화

def test_문자열_질환도_받는다_하위호환():
    """기존 프로필의 conditions: [당뇨] 형태를 깨뜨리지 않는다."""
    out = treatment.normalize_conditions(["당뇨"])
    assert out == [{"name": "당뇨"}]


def test_dict_질환_정규화():
    out = treatment.normalize_conditions([
        {"name": "고혈압", "since": "2023-05", "status": "관리중", "dept": "내과"}])
    assert out[0]["name"] == "고혈압" and out[0]["status"] == "관리중"


def test_화이트리스트_밖_필드는_버려진다():
    """병원 실명·증권번호류가 구조적으로 못 들어간다."""
    out = treatment.normalize_conditions([{
        "name": "고혈압", "hospital": "서울OO병원", "증권번호": "123-456",
        "환자번호": "A99", "dept": "내과"}])
    assert set(out[0].keys()) <= set(treatment.CONDITION_FIELDS)
    assert "서울OO병원" not in str(out) and "123-456" not in str(out)


def test_이름_없으면_버려진다():
    assert treatment.normalize_conditions([{"since": "2023-05"}]) == []
    assert treatment.normalize_medications([{"dose": "5mg"}]) == []


def test_알수없는_상태는_관리중으로():
    out = treatment.normalize_conditions([{"name": "고혈압", "status": "몰라요"}])
    assert out[0]["status"] == "관리중"


def test_예약은_날짜순_정렬():
    out = treatment.normalize_next_visits([
        {"date": "2026-12-01"}, {"date": "2026-09-15"}])
    assert [r["date"] for r in out] == ["2026-09-15", "2026-12-01"]


def test_condition_names_는_두_형태_모두_처리():
    assert treatment.condition_names({"conditions": ["당뇨"]}) == ["당뇨"]
    assert treatment.condition_names(
        {"conditions": [{"name": "당뇨", "status": "치료중"}]}) == ["당뇨"]
    assert treatment.condition_names({}) == []


# ---------------------------------------------------------------- 저장·조회

def test_저장_후_읽기_라운드트립(v):
    treatment.set_treatment(
        v, "나",
        conditions=[{"name": "고혈압", "since": "2023-05", "status": "관리중"}],
        medications=[{"name": "암로디핀", "dose": "5mg", "for": "고혈압"}],
        next_visits=[{"date": "2026-09-15", "dept": "내과"}])
    t = treatment.load_treatment(v, "나")
    assert t["conditions"][0]["name"] == "고혈압"
    assert t["medications"][0]["for"] == "고혈압"
    assert t["next_visits"][0]["date"] == "2026-09-15"


def test_리스트는_통째_교체된다_약_끊음(v):
    treatment.set_treatment(v, "나", medications=[{"name": "암로디핀"}])
    treatment.set_treatment(v, "나", medications=[])
    assert treatment.load_treatment(v, "나")["medications"] == []


def test_넘기지_않은_항목은_유지된다(v):
    treatment.set_treatment(v, "나", conditions=[{"name": "고혈압"}])
    treatment.set_treatment(v, "나", medications=[{"name": "암로디핀"}])
    t = treatment.load_treatment(v, "나")
    assert t["conditions"][0]["name"] == "고혈압"
    assert t["medications"][0]["name"] == "암로디핀"


def test_add_item_같은_이름은_교체(v):
    treatment.add_item(v, "나", "condition", {"name": "고혈압", "status": "치료중"})
    treatment.add_item(v, "나", "condition", {"name": "고혈압", "status": "관리중"})
    conds = treatment.load_treatment(v, "나")["conditions"]
    assert len(conds) == 1 and conds[0]["status"] == "관리중"


def test_질환_종료는_완치로_바뀐다(v):
    treatment.add_item(v, "나", "condition", {"name": "고혈압"})
    treatment.end_item(v, "나", "condition", "고혈압")
    t = treatment.load_treatment(v, "나")
    assert t["conditions"][0]["status"] == "완치"
    assert treatment.active_conditions(t) == []


def test_약_종료는_목록에서_제거(v):
    treatment.add_item(v, "나", "medication", {"name": "암로디핀"})
    treatment.end_item(v, "나", "medication", "암로디핀")
    assert treatment.load_treatment(v, "나")["medications"] == []


def test_없는_항목_종료는_오류(v):
    with pytest.raises(SystemExit):
        treatment.end_item(v, "나", "medication", "없는약")


def test_미등록_구성원은_거부(v):
    with pytest.raises(SystemExit):
        treatment.set_treatment(v, "없는사람", conditions=[{"name": "고혈압"}])


# ---------------------------------------------------------------- 예약 조회

def test_다가오는_예약_dday(v):
    treatment.set_treatment(v, "나", next_visits=[{"date": "2026-09-15"}])
    rows = treatment.upcoming_visits(v, dt.date(2026, 9, 1))
    assert rows[0]["days_left"] == 14 and rows[0]["soon"] is False


def test_임박한_예약은_soon(v):
    treatment.set_treatment(v, "나", next_visits=[{"date": "2026-09-05"}])
    rows = treatment.upcoming_visits(v, dt.date(2026, 9, 1))
    assert rows[0]["soon"] is True


def test_지난_예약은_제외(v):
    treatment.set_treatment(v, "나", next_visits=[{"date": "2026-08-01"}])
    assert treatment.upcoming_visits(v, dt.date(2026, 9, 1)) == []


def test_잘못된_날짜는_건너뛴다(v):
    treatment.set_treatment(v, "나", next_visits=[{"date": "언젠가"}])
    assert treatment.upcoming_visits(v, dt.date(2026, 9, 1)) == []


def test_예약_요약(v):
    treatment.set_treatment(v, "나", next_visits=[
        {"date": "2026-09-03"}, {"date": "2026-11-01"}])
    s = treatment.upcoming_summary(v, dt.date(2026, 9, 1))
    assert s == {"count": 2, "next_date": "2026-09-03", "soon": 1}


def test_예약_결과는_JSON_직렬화_가능(v):
    """report/API 에 실리므로 Path 같은 객체가 섞이면 안 된다."""
    import json
    treatment.set_treatment(v, "나", next_visits=[{"date": "2026-09-15"}])
    json.dumps(treatment.upcoming_visits(v, dt.date(2026, 9, 1)))


# ---------------------------------------------------------------- 질환→태그 매핑

def test_disease_tag_매핑():
    assert recommend.disease_tag("고혈압") == "혈압"
    assert recommend.disease_tag("이상지질혈증") == "지질"
    assert recommend.disease_tag("모르는병") is None


def test_가족력_태그는_같은_표를_쓴다():
    assert recommend.family_history_tags(["고혈압", "당뇨"]) == ["혈압", "혈당"]


# ---------------------------------------------------------------- riskscore 연동

def test_혈압약_복약이면_치료중으로_계산되고_근거가_남는다():
    inputs = riskscore.cvd_inputs(
        age=55, sex="M",
        latest={"수축기혈압": {"value": 140}, "총콜레스테롤": {"value": 213},
               "HDL": {"value": 50}},
        profile={"medications": [{"name": "암로디핀", "for": "고혈압"}]})
    assert inputs["bp_treated"] is True
    assert any("혈압" in a for a in inputs["assumptions"])


def test_명시_설정이_복약_유추보다_우선():
    inputs = riskscore.cvd_inputs(
        age=55, sex="M",
        latest={"수축기혈압": {"value": 140}, "총콜레스테롤": {"value": 213},
               "HDL": {"value": 50}},
        profile={"bp_treated": False,
                "medications": [{"name": "암로디핀", "for": "고혈압"}]})
    assert inputs["bp_treated"] is False


def test_당뇨_추정은_dict_질환에서도_동작():
    inputs = riskscore.cvd_inputs(
        age=55, sex="M",
        latest={"수축기혈압": {"value": 140}, "총콜레스테롤": {"value": 213},
               "HDL": {"value": 50}},
        profile={"conditions": [{"name": "당뇨", "status": "치료중"}]})
    assert inputs["diabetes"] is True
