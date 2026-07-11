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


def test_mask_for_external_strips_measurements():
    out = anonymize.mask_for_external("혈압 120/80 mmHg 체중 72kg 검사", aliases={})
    assert "120" not in out and "72" not in out


def test_mask_for_external_keeps_year():
    out = anonymize.mask_for_external("2025 건강검진 입력", aliases={})
    assert "2025" in out
