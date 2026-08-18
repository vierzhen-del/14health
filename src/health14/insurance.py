"""보험 가입정보 · 실비(실손) 청구 관리.

보험 노트는 구성원별로 `구성원/<관계호칭>/보험/<보험사>-<상품명>.md` 에 저장한다.

**증권번호·고객번호는 스키마에 아예 없다.** 필드를 만들지 않았으므로 실수로도
저장될 수 없다(사용자 결정). 청구할 때 필요한 번호는 보험사 앱에서 확인한다.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from health14 import anonymize, vault

INSURANCE_DIR = "보험"

# 저장 허용 필드 — 이 목록 밖의 값은 노트에 기록하지 않는다
FIELDS = ("보험사", "상품명", "종류", "가입일", "갱신일", "보험료",
          "자기부담금", "보장한도", "보장항목")

KINDS = ["실손", "암", "치아", "상해", "질병", "운전자", "종신", "간병", "기타"]

# 실손보험 청구권 소멸시효(상법 662조) — 보험금 청구는 3년
CLAIM_LIMIT_DAYS = 365 * 3
# 이 일수가 지나면 "서두르세요" 경고
CLAIM_WARN_DAYS = CLAIM_LIMIT_DAYS - 90

CLAIM_STATES = ["미청구", "청구중", "수령완료", "대상아님"]


def _safe_name(text: str) -> str:
    return re.sub(r"[^\w가-힣]+", "-", text).strip("-") or "보험"


def insurance_dir(vault_path: Path, relation: str) -> Path:
    return vault_path / vault.MEMBERS_DIR / relation / INSURANCE_DIR


def add_insurance(vault_path: Path, relation: str, data: Dict[str, Any]) -> Path:
    """보험 가입정보 저장. 허용 필드만 기록한다."""
    if vault.get_member(vault_path, relation) is None:
        raise SystemExit(f"등록되지 않은 구성원입니다: {relation}")

    company = (data.get("보험사") or "").strip()
    product = (data.get("상품명") or "").strip()
    if not company or not product:
        raise SystemExit("보험사와 상품명은 필수입니다.")

    meta: Dict[str, Any] = {"type": "insurance", "member": relation}
    for key in FIELDS:
        value = data.get(key)
        if value in (None, "", []):
            continue
        if key == "보장항목":
            items = value if isinstance(value, list) else str(value).split(",")
            meta[key] = [anonymize.anonymize(str(v).strip()) for v in items if str(v).strip()]
        elif key == "자기부담금" and "%" in str(value):
            meta[key] = str(value).strip()  # 정률 자기부담금(예: "20%")은 그대로 보존
        elif key in ("보험료", "자기부담금", "보장한도"):
            meta[key] = _to_won(value)
        else:
            meta[key] = anonymize.anonymize(str(value).strip())

    path = insurance_dir(vault_path, relation) / f"{_safe_name(company)}-{_safe_name(product)}.md"
    lines = [f"# {company} {product}", ""]
    for key in FIELDS:
        if key not in meta:
            continue
        value = meta[key]
        if isinstance(value, list):
            value = ", ".join(value)
        elif key in ("보험료", "자기부담금", "보장한도") and isinstance(value, int):
            value = f"{value:,}원"
        lines.append(f"- {key}: {value}")
    lines += ["", "> 증권번호·고객번호는 저장하지 않습니다 — 청구 시 보험사 앱에서 확인하세요."]
    vault.write_note(path, meta, "\n".join(lines) + "\n")
    return path


def _to_won(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d]", "", str(value or ""))
    return int(digits) if digits else None


def load_insurances(vault_path: Path, relation: str) -> List[Dict[str, Any]]:
    folder = insurance_dir(vault_path, relation)
    result: List[Dict[str, Any]] = []
    if folder.exists():
        for f in sorted(folder.glob("*.md")):
            meta, _ = vault.read_note(f)
            if meta.get("type") == "insurance":
                meta["_path"] = f
                result.append(meta)
    return result


def load_all_insurances(vault_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    return {m["relation"]: load_insurances(vault_path, m["relation"])
            for m in vault.load_members(vault_path)}


def has_medical_insurance(vault_path: Path, relation: str) -> bool:
    """실손(실비) 보험 보유 여부."""
    return any(i.get("종류") == "실손" for i in load_insurances(vault_path, relation))


# ---------------------------------------------------------------- 실비 청구

def normalize_claim(data: Any) -> Dict[str, Any]:
    """진료 노트에 저장할 청구 정보 정규화."""
    if not data:
        return {}
    if isinstance(data, str):
        data = {"상태": data}
    state = (data.get("상태") or "").strip()
    if state not in CLAIM_STATES:
        state = "미청구"
    claim: Dict[str, Any] = {"상태": state}
    if data.get("청구일"):
        claim["청구일"] = str(data["청구일"])[:10]
    amount = _to_won(data.get("수령액"))
    if amount is not None:
        claim["수령액"] = amount
    if data.get("보험"):
        claim["보험"] = anonymize.anonymize(str(data["보험"]).strip())
    return claim


def pending_claims(vault_path: Path,
                   today: Optional[dt.date] = None) -> List[Dict[str, Any]]:
    """실비 청구가 가능한데 아직 안 한 진료 건.

    조건: 본인부담금이 있고 · 실손보험 보유자이며 · 상태가 미청구/미기재.
    소멸시효(3년)가 지난 건은 `만료` 로 표시해 함께 돌려준다.
    """
    today = today or dt.date.today()
    result: List[Dict[str, Any]] = []
    for member in vault.load_members(vault_path):
        relation = member["relation"]
        if not has_medical_insurance(vault_path, relation):
            continue
        display = member.get("display") or relation
        for visit in vault.load_visits(vault_path, relation):
            cost = visit.get("cost") or {}
            paid = cost.get("본인부담금") or cost.get("납부금액")
            if not paid:
                continue
            claim = visit.get("claim") or {}
            if claim.get("상태") in ("수령완료", "청구중", "대상아님"):
                continue
            try:
                date = dt.date.fromisoformat(str(visit.get("date"))[:10])
            except (TypeError, ValueError):
                continue
            days = (today - date).days
            result.append({
                "relation": relation,
                "display": display,
                "date": date.isoformat(),
                "hospital": visit.get("hospital", ""),
                "amount": paid,
                "days_elapsed": days,
                "days_left": CLAIM_LIMIT_DAYS - days,
                "expired": days > CLAIM_LIMIT_DAYS,
                "urgent": CLAIM_WARN_DAYS <= days <= CLAIM_LIMIT_DAYS,
                "note": visit["_path"].relative_to(vault_path).as_posix()
                        if visit.get("_path") else "",
            })
    result.sort(key=lambda r: r["days_left"])
    return result


def claim_summary(vault_path: Path,
                  today: Optional[dt.date] = None) -> Dict[str, Any]:
    """미청구 건수·금액 요약 (홈 배너용)."""
    pending = [p for p in pending_claims(vault_path, today) if not p["expired"]]
    return {
        "count": len(pending),
        "total": sum(p["amount"] for p in pending),
        "urgent": sum(1 for p in pending if p["urgent"]),
    }
