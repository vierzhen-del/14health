from health14 import parse


def test_chat_style_text():
    r = parse.parse_checkup_text("나 2025년 검진 혈압 138/88 체중 80kg 공복혈당 115")
    assert r["relation"] == "나"
    assert r["year"] == 2025
    assert r["metrics"]["수축기혈압"] == 138
    assert r["metrics"]["이완기혈압"] == 88
    assert r["metrics"]["체중"] == 80
    assert r["metrics"]["공복혈당"] == 115


def test_report_style_aliases():
    text = """
    검진일: 2024-11-02
    SBP 132  DBP 85
    HbA1c: 5.9 %
    GOT 35 / GPT 52
    γ-GTP 88
    LDL-C 145 mg/dL
    몸무게 78.5
    """
    r = parse.parse_checkup_text(text)
    assert r["date"] == "2024-11-02"
    assert r["year"] == 2024
    m = r["metrics"]
    assert m["수축기혈압"] == 132 and m["이완기혈압"] == 85
    assert m["당화혈색소"] == 5.9
    assert m["AST"] == 35 and m["ALT"] == 52
    assert m["감마GTP"] == 88
    assert m["LDL"] == 145
    assert m["체중"] == 78.5


def test_bare_bp_pattern():
    r = parse.parse_checkup_text("측정 결과 120/80 이었습니다")
    assert r["metrics"]["수축기혈압"] == 120
    assert r["metrics"]["이완기혈압"] == 80


def test_md_our_checkup_format():
    content = """---
type: checkup
member: 나
year: 2025
date: '2025-11-02'
metrics:
  수축기혈압: 138
  체중: 80
---

# 나 2025 건강검진
"""
    r = parse.parse_md_content(content)
    assert r["kind"] == "checkup"
    assert r["data"]["relation"] == "나"
    assert r["data"]["year"] == 2025
    assert r["data"]["metrics"]["수축기혈압"] == 138


def test_md_our_visit_format():
    content = """---
type: visit
member: 딸
date: '2026-06-20'
hospital: 소아과
symptoms:
- 기침
diagnosis: 감기
medications: []
---
"""
    r = parse.parse_md_content(content)
    assert r["kind"] == "visit"
    assert r["data"]["hospital"] == "소아과"
    assert r["data"]["symptoms"] == ["기침"]


def test_md_generic_table():
    content = """# 2023 검진 결과

| 항목 | 수치 |
|---|---|
| 혈압 | 128/82 |
| 콜레스테롤 | 210 |
| 몸무게 | 76 kg |
"""
    r = parse.parse_md_content(content)
    assert r["kind"] == "parsed"
    m = r["data"]["metrics"]
    assert m["수축기혈압"] == 128 and m["이완기혈압"] == 82
    assert m["총콜레스테롤"] == 210
    assert m["체중"] == 76
    assert r["data"]["year"] == 2023


# ---------------------------------------- 진료명세서·약국영수증

STATEMENT = """
진 료 비 계 산 서 · 영 수 증
환자명: 홍길동    등록번호: 12345678
진료기간: 2026-07-25 ~ 2026-07-25
진료과: 응급의학과      병원: 서울OO병원
[급여] 진찰료 15,000  검사료 48,000
본인부담금 34,500   공단부담금 60,500
총액 95,000 원    납부금액 34,500 원
"""

PHARMACY = """
OO약국  032-123-4567
조제일자 2026-07-25
처방전 발행 의료기관: 서울OO병원 소아청소년과
1. 록소프로펜나트륨정 60mg  1일3회 3일분
2. 알마겔현탁액           1일3회 3일분
본인부담금 4,800원
"""

CHECKUP_SHEET = """
2025년 건강검진 결과
혈압: 138/88 mmHg   공복혈당: 115 mg/dL
체중 80 kg  신장 174 cm
"""


def test_detect_document_types():
    assert parse.detect_document_type(STATEMENT) == "statement"
    assert parse.detect_document_type(PHARMACY) == "pharmacy"
    assert parse.detect_document_type(CHECKUP_SHEET) == "checkup"


def test_parse_statement_extracts_department_and_cost():
    r = parse.parse_visit_text(STATEMENT)
    assert r["date"] == "2026-07-25"
    assert r["hospital"] == "응급의학과"
    assert r["cost"]["본인부담금"] == 34500
    assert r["cost"]["총액"] == 95000


def test_parse_pharmacy_extracts_medications():
    r = parse.parse_visit_text(PHARMACY)
    assert r["date"] == "2026-07-25"
    assert "록소프로펜나트륨정" in r["medications"]
    assert "알마겔현탁액" in r["medications"]
    assert r["cost"]["본인부담금"] == 4800


def test_parse_document_routes_to_right_form():
    assert parse.parse_document(STATEMENT)["kind"] == "visit"
    assert parse.parse_document(PHARMACY)["kind"] == "visit"
    assert parse.parse_document(CHECKUP_SHEET)["kind"] == "checkup"


def test_visit_parser_ignores_patient_identifiers():
    """파서는 환자 실명·등록번호를 구조화 결과에 담지 않는다."""
    import json
    payload = json.dumps(parse.parse_visit_text(STATEMENT), ensure_ascii=False)
    assert "홍길동" not in payload and "12345678" not in payload


def test_labeled_medications():
    r = parse.parse_visit_text("처방약: 타이레놀, 항생제\n진료과: 내과\n진료일 2026-03-02")
    assert r["medications"] == ["타이레놀", "항생제"]
    assert r["hospital"] == "내과"


# ---------------------------------------- 영수증 → 가족 자동매칭

def test_match_member_by_registered_name():
    r = parse.match_member(STATEMENT, {"홍길동": "나"}, ["나", "부인"])
    assert r["relation"] == "나" and r["matched_by"] == "실명"


def test_match_member_prefers_longer_name():
    aliases = {"홍길": "부인", "홍길동": "나"}
    assert parse.match_member(STATEMENT, aliases, ["나", "부인"])["relation"] == "나"


def test_match_member_by_relation_word():
    text = "진료과: 내과\n환자명: 아들\n진료일 2026-07-25"
    r = parse.match_member(text, {}, ["나", "아들"])
    assert r["relation"] == "아들" and r["matched_by"] == "관계호칭"


def test_match_member_no_substring_false_positive():
    """'나'가 '나트륨'·'하나'에 걸려 오매칭되면 안 된다."""
    text = "1. 록소프로펜나트륨정 60mg\n조제일자 2026-07-25"
    assert parse.match_member(text, {}, ["나", "아들"])["relation"] is None


def test_match_member_custom_relation_label():
    text = "환자명: 아들(첫째)\n진료과: 소아청소년과"
    r = parse.match_member(text, {}, ["아들(첫째)", "아들(둘째)"])
    assert r["relation"] == "아들(첫째)"


def test_match_member_returns_none_when_unknown():
    r = parse.match_member(PHARMACY, {"홍길동": "나"}, ["나"])
    assert r["relation"] is None and r["matched_by"] is None


def test_extract_patient_name():
    assert parse.extract_patient_name(STATEMENT) == "홍길동"
    assert parse.extract_patient_name("아무 내용 없음") is None
