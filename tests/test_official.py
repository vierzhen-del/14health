"""공단·심평원에서 내려받은 공식 파일 가져오기."""
import pytest

from health14 import anonymize, official

CHECKUP_NOTICE = """국민건강보험공단
일반건강검진 결과 통보서
성명: 홍길동          검진일자: 2026-04-11
계측검사
  신장                 174.0   cm
  체중                 79.5    kg
  체질량지수           26.3
혈액검사
  공복혈당             118     (정상 100 미만)
  총콜레스테롤         215
  혈색소               15.2
판정: 고혈압 및 당뇨 의심 — 2차 검진 권고
"""

VISIT_NOTICE = """국민건강보험공단
진료받은 내용 안내
성명: 홍길동
진료개시일 2026-05-09   요양기관 종별: 정형외과
투약내역: 소염제, 진통제
본인부담금 18,000원
"""


def test_is_official_detects_public_forms():
    assert official.is_official(CHECKUP_NOTICE)
    assert official.is_official(VISIT_NOTICE)
    assert not official.is_official("OO약국 조제일자 2026-07-25")


def test_official_checkup_extracts_table_rows():
    r = official.parse_official(CHECKUP_NOTICE)
    assert r["doc_type"] == "official_checkup" and r["kind"] == "checkup"
    m = r["data"]["metrics"]
    assert m["신장"] == 174 and m["체중"] == 79.5
    assert m["BMI"] == 26.3            # "체질량지수" 별칭 + 표 형태 보완
    assert m["공복혈당"] == 118
    assert m["총콜레스테롤"] == 215
    assert r["data"]["year"] == 2026


def test_official_visit_routes_to_visit_form():
    r = official.parse_official(VISIT_NOTICE)
    assert r["doc_type"] == "official_visit" and r["kind"] == "visit"
    assert r["data"]["date"] == "2026-05-09"
    assert r["data"]["hospital"] == "정형외과"
    assert r["data"]["cost"]["본인부담금"] == 18000


def test_non_official_falls_back_to_general_parser(tmp_path):
    f = tmp_path / "영수증.txt"
    f.write_text("OO약국\n조제일자 2026-07-25\n1. 타이레놀정 500mg\n본인부담금 4,800원",
                 encoding="utf-8")
    r = official.parse_file(f)
    assert r["doc_type"] == "pharmacy"


def test_official_text_still_gets_anonymized(vault_path):
    """공식 파일의 실명도 저장 전 익명화를 거친다."""
    masked = anonymize.anonymize(CHECKUP_NOTICE, aliases={})
    assert "홍길동" not in masked


def test_parse_path_reads_folder(tmp_path):
    (tmp_path / "a.txt").write_text(CHECKUP_NOTICE, encoding="utf-8")
    (tmp_path / "b.txt").write_text(VISIT_NOTICE, encoding="utf-8")
    (tmp_path / "무시.png").write_bytes(b"not text")
    results = official.parse_path(tmp_path)
    assert len(results) == 2
    assert {r["kind"] for r in results} == {"checkup", "visit"}


def test_unsupported_extension_is_explained(tmp_path):
    f = tmp_path / "x.docx"
    f.write_bytes(b"zip")
    with pytest.raises(SystemExit) as e:
        official.extract_text(f)
    assert "지원하지 않는 형식" in str(e.value)


def test_pdf_without_pdftotext_gives_install_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(official, "pdftotext_available", lambda: False)
    f = tmp_path / "결과.pdf"
    f.write_bytes(b"%PDF-1.4")
    with pytest.raises(SystemExit) as e:
        official.extract_text(f)
    assert "poppler" in str(e.value)
