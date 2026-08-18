from health14 import anonymize


def test_alias_replacement():
    out = anonymize.anonymize("김영희 혈압 정상", aliases={"김영희": "부인"})
    assert "김영희" not in out
    assert out.startswith("부인")


def test_rrn_and_phone_masked():
    out = anonymize.anonymize("주민 800101-1234567 연락처 010-1234-5678", aliases={})
    assert "1234567" not in out
    assert "[주민번호]" in out and "[전화번호]" in out


def test_honorific_name_masked():
    out = anonymize.anonymize("박순자님 진료 예약", aliases={})
    assert "박순자" not in out
    assert "[가족]" in out


def test_receipt_labeled_name_masked():
    """진료명세서·영수증의 '환자명: OOO' 형태 실명 마스킹."""
    out = anonymize.anonymize("환자명: 홍길동    등록번호: 12345678", aliases={})
    assert "홍길동" not in out and "12345678" not in out
    assert "[가족]" in out and "[식별번호]" in out


def test_receipt_variants_masked():
    for text, name in [("성명 김철수", "김철수"),
                       ("수진자: 이영희", "이영희"),
                       ("차트번호: A-98211", "A-98211")]:
        out = anonymize.anonymize(text, aliases={})
        assert name not in out, f"{text} 에서 {name} 이 남음"


def test_relation_kept_in_labeled_name():
    """관계호칭은 마스킹하지 않는다."""
    assert "아들" in anonymize.anonymize("환자명: 아들", aliases={})
    assert "부인" in anonymize.anonymize("부인님 처방전", aliases={})


def test_partially_masked_rrn():
    out = anonymize.anonymize("주민번호 120315-3******", aliases={})
    assert "120315" not in out and "[주민번호]" in out


def test_receipt_keeps_date_and_amount():
    """날짜·금액은 진료 기록에 필요하므로 보존."""
    out = anonymize.anonymize("진료일 2026-07-25 본인부담금 34,500원", aliases={})
    assert "2026-07-25" in out and "34,500" in out


def test_mask_for_external_strips_measurements():
    out = anonymize.mask_for_external("혈압 120/80 mmHg 체중 72kg 검사", aliases={})
    assert "120" not in out and "72" not in out


def test_mask_for_external_keeps_year():
    out = anonymize.mask_for_external("2025 건강검진 입력", aliases={})
    assert "2025" in out
