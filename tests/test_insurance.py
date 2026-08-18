"""보험 가입정보 · 실비 청구 관리."""
import datetime as dt
import json

import pytest

from health14 import insurance, intake, vault


def _member(vault_path):
    vault.add_member(vault_path, "나", 1978, "M", "본인")


def _add_silson(vault_path, **extra):
    data = {"보험사": "삼성화재", "상품명": "다이렉트 실손", "종류": "실손"}
    data.update(extra)
    return insurance.add_insurance(vault_path, "나", data)


def test_add_and_load_insurance(vault_path):
    _member(vault_path)
    path = _add_silson(vault_path, 가입일="2020-01-15", 보험료="32,000")
    assert path.exists()
    items = insurance.load_insurances(vault_path, "나")
    assert len(items) == 1
    assert items[0]["보험사"] == "삼성화재"
    assert items[0]["보험료"] == 32000


def test_policy_number_cannot_be_stored(vault_path):
    """증권번호·고객번호는 스키마에 없어 넘겨도 저장되지 않는다."""
    _member(vault_path)
    path = _add_silson(vault_path, 증권번호="ABC-123456", 고객번호="C99887766",
                       주민번호="800101-1234567")
    text = path.read_text(encoding="utf-8")
    for secret in ("ABC-123456", "C99887766", "800101"):
        assert secret not in text, f"{secret} 가 노트에 저장됨"
    meta = insurance.load_insurances(vault_path, "나")[0]
    assert "증권번호" not in meta and "고객번호" not in meta


def test_percentage_deductible_preserved(vault_path):
    """정률 자기부담금(20%)이 금액으로 잘못 변환되지 않는다."""
    _member(vault_path)
    _add_silson(vault_path, 자기부담금="20%")
    assert insurance.load_insurances(vault_path, "나")[0]["자기부담금"] == "20%"


def test_coverage_list_split(vault_path):
    _member(vault_path)
    _add_silson(vault_path, 보장항목="입원, 통원, 약제비")
    assert insurance.load_insurances(vault_path, "나")[0]["보장항목"] == [
        "입원", "통원", "약제비"]


def test_requires_company_and_product(vault_path):
    _member(vault_path)
    with pytest.raises(SystemExit):
        insurance.add_insurance(vault_path, "나", {"보험사": "삼성화재"})


def test_has_medical_insurance(vault_path):
    _member(vault_path)
    assert insurance.has_medical_insurance(vault_path, "나") is False
    _add_silson(vault_path)
    assert insurance.has_medical_insurance(vault_path, "나") is True


# ---------------------------------------------------------------- 실비 청구

def test_normalize_claim_defaults_to_uncllaimed():
    assert insurance.normalize_claim("이상한상태")["상태"] == "미청구"
    assert insurance.normalize_claim({"상태": "수령완료", "수령액": "9,600"}) == {
        "상태": "수령완료", "수령액": 9600}
    assert insurance.normalize_claim(None) == {}


def test_claim_saved_to_visit_note(vault_path):
    _member(vault_path)
    path = intake.apply_visit(vault_path, "나", {
        "date": "2026-03-14", "hospital": "내과", "symptoms": ["기침"],
        "cost": {"본인부담금": "12,000"}, "claim": {"상태": "수령완료", "수령액": "9,600"}})
    meta, body = vault.read_note(path)
    assert meta["claim"]["상태"] == "수령완료"
    assert meta["claim"]["수령액"] == 9600
    assert "실비청구" in body


def test_pending_claims_needs_insurance(vault_path):
    """실손보험이 없으면 미청구 목록에 잡히지 않는다."""
    _member(vault_path)
    vault.add_visit(vault_path, "나", "2026-03-14", "내과", [], "", [],
                    "", {"본인부담금": 12000})
    assert insurance.pending_claims(vault_path) == []
    _add_silson(vault_path)
    assert len(insurance.pending_claims(vault_path)) == 1


def test_pending_excludes_settled(vault_path):
    _member(vault_path)
    _add_silson(vault_path)
    intake.apply_visit(vault_path, "나", {
        "date": "2026-03-14", "hospital": "내과",
        "cost": {"본인부담금": 12000}, "claim": {"상태": "수령완료"}})
    intake.apply_visit(vault_path, "나", {
        "date": "2026-04-02", "hospital": "치과",
        "cost": {"본인부담금": 45000}, "claim": {"상태": "미청구"}})
    pending = insurance.pending_claims(vault_path)
    assert [p["hospital"] for p in pending] == ["치과"]


def test_pending_ignores_free_visits(vault_path):
    """본인부담금이 없는 기록은 청구 대상이 아니다."""
    _member(vault_path)
    _add_silson(vault_path)
    vault.add_visit(vault_path, "나", "2026-03-14", "내과", [], "", [])
    assert insurance.pending_claims(vault_path) == []


def test_claim_deadline_flags(vault_path):
    _member(vault_path)
    _add_silson(vault_path)
    today = dt.date(2026, 8, 18)
    vault.add_visit(vault_path, "나", "2026-08-01", "내과", [], "", [],
                    "", {"본인부담금": 10000})                      # 최근
    vault.add_visit(vault_path, "나", "2023-09-01", "치과", [], "", [],
                    "", {"본인부담금": 20000})                      # 시효 임박
    vault.add_visit(vault_path, "나", "2020-01-01", "안과", [], "", [],
                    "", {"본인부담금": 30000})                      # 시효 경과
    by_hospital = {p["hospital"]: p
                   for p in insurance.pending_claims(vault_path, today)}
    assert by_hospital["내과"]["urgent"] is False
    assert by_hospital["내과"]["expired"] is False
    assert by_hospital["치과"]["urgent"] is True
    assert by_hospital["안과"]["expired"] is True


def test_claim_summary_excludes_expired(vault_path):
    _member(vault_path)
    _add_silson(vault_path)
    today = dt.date(2026, 8, 18)
    vault.add_visit(vault_path, "나", "2026-08-01", "내과", [], "", [],
                    "", {"본인부담금": 10000})
    vault.add_visit(vault_path, "나", "2020-01-01", "안과", [], "", [],
                    "", {"본인부담금": 30000})
    summary = insurance.claim_summary(vault_path, today)
    assert summary["count"] == 1 and summary["total"] == 10000


def test_pending_claims_json_has_no_identifiers(vault_path):
    _member(vault_path)
    _add_silson(vault_path, 증권번호="ABC-123456")
    vault.add_visit(vault_path, "나", "2026-03-14", "내과", [], "", [],
                    "", {"본인부담금": 12000})
    payload = json.dumps(insurance.pending_claims(vault_path), ensure_ascii=False)
    assert "ABC-123456" not in payload
