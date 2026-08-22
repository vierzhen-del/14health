"""AI 상담 브리핑 — 내용 정확성 + 개인정보 누출 방지 핀."""
import datetime as dt
import json
import pathlib
import re

import pytest

from health14 import consult, treatment, vault

TODAY = dt.date(2026, 6, 1)


@pytest.fixture
def v(tmp_path):
    path = tmp_path / "vault"
    vault.init_vault(path)
    vault.add_member(path, "나", 1970, "M")
    vault.add_checkup(path, "나", 2025, {
        "수축기혈압": 142, "이완기혈압": 90, "공복혈당": 118,
        "총콜레스테롤": 235, "HDL": 40})
    vault.add_family_history(path, "부", "고혈압")
    treatment.set_treatment(
        path, "나",
        conditions=[{"name": "고혈압", "status": "관리중", "dept": "내과"}],
        medications=[{"name": "암로디핀", "dose": "5mg", "for": "고혈압"}],
        next_visits=[{"date": "2026-09-15", "dept": "내과"}])
    return path


# ---------------------------------------------------------------- 내용

def test_브리핑_기본_구성(v):
    b = consult.build_briefing(v, "나", TODAY)
    p = b["구성원"][0]
    assert p["대상"] == "나" and p["나이"] == 56
    assert p["가족력"] == [{"관계": "부", "질환": "고혈압"}]
    assert p["현재_치료중"][0]["질환"] == "고혈압"
    assert p["복약중"][0]["약"] == "암로디핀"
    assert p["다음_예약"][0]["날짜"] == "2026-09-15"
    assert p["교차_소견"]  # 교차 소견이 실제로 잡힌다


def test_수치는_들어간다_상담의_목적(v):
    """mask_for_external 과 달리 브리핑은 수치를 유지해야 쓸모가 있다."""
    text = consult.render_text(consult.build_briefing(v, "나", TODAY))
    assert "142" in text and "수축기혈압" in text


def test_관계_생략하면_가족_전체(v):
    vault.add_member(v, "부인", 1972, "F")
    b = consult.build_briefing(v, None, TODAY)
    assert {p["대상"] for p in b["구성원"]} == {"나", "부인"}


def test_없는_구성원은_오류(v):
    with pytest.raises(SystemExit):
        consult.build_briefing(v, "없는사람", TODAY)


def test_구성원_없으면_오류(tmp_path):
    empty = tmp_path / "empty"
    vault.init_vault(empty)
    with pytest.raises(SystemExit):
        consult.build_briefing(empty, None, TODAY)


def test_추천_질문이_소견에서_생성된다(v):
    b = consult.build_briefing(v, "나", TODAY)
    qs = b["추천_질문"]
    assert qs and any("용량 조절" in q for q in qs)
    assert len(qs) == len(set(qs))  # 중복 없음


def test_면책_문구가_반드시_포함된다(v):
    text = consult.render_text(consult.build_briefing(v, "나", TODAY))
    assert "의학적 진단이 아닙니다" in text


def test_브리핑은_JSON_직렬화_가능(v):
    """MCP·API 로 나가므로 Path 같은 객체가 섞이면 안 된다."""
    json.dumps(consult.build_briefing(v, "나", TODAY), ensure_ascii=False)


# ---------------------------------------------------------------- 누출 핀

def test_실명_주민번호가_브리핑에_새지_않는다(v):
    """저장 경로에 개인정보를 주입해도 브리핑 텍스트에 남지 않아야 한다."""
    vault.add_visit(v, "나", "2026-03-01", "내과",
                    symptoms=["환자명 홍길동 두통"],
                    diagnosis="환자 홍길동 / 주민번호 900101-1234567",
                    medications=["등록번호 A-99887 타이레놀"],
                    memo="연락처 010-1234-5678")
    text = consult.render_text(consult.build_briefing(v, "나", TODAY))
    for leaked in ("홍길동", "900101-1234567", "010-1234-5678", "A-99887"):
        assert leaked not in text, f"브리핑에 개인정보가 남았습니다: {leaked}"


def test_브리핑에_주민번호_전화번호_패턴이_없다(v):
    text = consult.render_text(consult.build_briefing(v, "나", TODAY))
    assert not re.search(r"\d{6}\s*-\s*[1-4]\d{6}", text)
    assert not re.search(r"01[016-9]-?\d{3,4}-?\d{4}", text)


def test_앱은_새_외부_통신_경로를_만들지_않는다():
    """구조적 핀 — HTTP 클라이언트는 hira·notion_log 둘뿐이어야 한다."""
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "health14"
    offenders = []
    for f in src.glob("*.py"):
        body = f.read_text(encoding="utf-8")
        if re.search(r"\b(urllib\.request|http\.client|requests\.|httpx\.)", body):
            offenders.append(f.name)
    assert sorted(offenders) == ["hira.py", "notion_log.py"], (
        f"새 외부 통신 경로가 생겼습니다: {offenders}")


def test_consult_모듈은_아무것도_전송하지_않는다():
    import inspect
    src = inspect.getsource(consult)
    for banned in ("urlopen", "requests", "httpx", "socket", "post("):
        assert banned not in src, f"consult.py 에 전송 코드가 있습니다: {banned}"
