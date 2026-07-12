"""검진/진료 구조화 입력 적용 — CLI note write와 웹앱이 공유하는 로직.

혈압 문자열 분리, BMI 자동계산, 익명화, 이력 로그 기록까지 한 곳에서 처리한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from health14 import anonymize, vault


def _to_number(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return value
    try:
        f = float(value)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return value


def apply_checkup(vault_path: Path, relation: str, data: Dict[str, Any]) -> Path:
    metrics: Dict[str, Any] = dict(data.get("metrics") or {})
    bp = metrics.pop("혈압", None)
    if isinstance(bp, str) and "/" in bp:
        s, _, d = bp.partition("/")
        metrics.setdefault("수축기혈압", _to_number(s))
        metrics.setdefault("이완기혈압", _to_number(d))
    metrics = {k: _to_number(v) for k, v in metrics.items()}
    if "BMI" not in metrics and "신장" in metrics and "체중" in metrics:
        h = float(metrics["신장"]) / 100
        metrics["BMI"] = round(float(metrics["체중"]) / (h * h), 1)
    memo = anonymize.anonymize(data.get("memo", ""))
    year = int(data["year"])
    path = vault.add_checkup(vault_path, relation, year, metrics, memo, data.get("date"))
    vault.log_action(vault_path, relation, "검진입력", f"{year} 건강검진 입력", path)
    return path


def apply_visit(vault_path: Path, relation: str, data: Dict[str, Any]) -> Path:
    symptoms = [anonymize.anonymize(s) for s in data.get("symptoms", []) if s]
    medications = [anonymize.anonymize(m) for m in data.get("medications", []) if m]
    diagnosis = anonymize.anonymize(data.get("diagnosis", ""))
    memo = anonymize.anonymize(data.get("memo", ""))
    hospital = data.get("hospital") or "진료"
    path = vault.add_visit(vault_path, relation, data["date"], hospital,
                           symptoms, diagnosis, medications, memo)
    vault.log_action(vault_path, relation, "진료입력", f"{hospital} 진료 기록", path)
    return path
