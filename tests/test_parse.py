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
