"""자유 텍스트·OCR 결과·MD 파일에서 검진 데이터를 추출하는 규칙 기반 파서.

대화창 입력("나 2025년 혈압 138/88 체중 80kg"), tesseract OCR 출력,
검진결과지 스타일 텍스트, 옵시디안 노트 md를 공통 구조로 변환한다.
추출 결과는 항상 사용자 확인(폼 프리필)을 거친 뒤 저장된다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import yaml

from health14 import vault

# 표준 항목명 ← 결과지·대화에서 흔히 쓰는 별칭 (긴 별칭부터 매칭)
METRIC_ALIASES: Dict[str, List[str]] = {
    "수축기혈압": ["수축기혈압", "수축기 혈압", "수축기", "최고혈압", "SBP"],
    "이완기혈압": ["이완기혈압", "이완기 혈압", "이완기", "최저혈압", "DBP"],
    "공복혈당": ["공복혈당", "공복 혈당", "식전혈당", "식전 혈당", "FBS", "공복시혈당"],
    "식후혈당": ["식후혈당", "식후 혈당", "식후2시간혈당", "PP2"],
    "당화혈색소": ["당화혈색소", "HbA1c", "HBA1C", "A1C", "당화 혈색소"],
    "체중": ["체중", "몸무게", "weight"],
    "신장": ["신장", "키", "height"],
    "BMI": ["BMI", "체질량지수", "체질량 지수"],
    "허리둘레": ["허리둘레", "허리 둘레", "복부둘레"],
    "총콜레스테롤": ["총콜레스테롤", "총 콜레스테롤", "콜레스테롤", "Total Cholesterol", "TC"],
    "LDL": ["LDL콜레스테롤", "LDL-C", "LDL 콜레스테롤", "LDL", "저밀도"],
    "HDL": ["HDL콜레스테롤", "HDL-C", "HDL 콜레스테롤", "HDL", "고밀도"],
    "중성지방": ["중성지방", "트리글리세라이드", "Triglyceride", "TG"],
    "AST": ["AST", "GOT", "AST(GOT)"],
    "ALT": ["ALT", "GPT", "ALT(GPT)"],
    "감마GTP": ["감마GTP", "감마지티피", "γ-GTP", "r-GTP", "GGT", "감마-GTP"],
    "크레아티닌": ["크레아티닌", "혈청크레아티닌", "Creatinine", "Cr"],
    "eGFR": ["eGFR", "사구체여과율", "신사구체여과율", "GFR"],
    "혈색소": ["혈색소", "헤모글로빈", "Hemoglobin", "Hb"],
    "요산": ["요산", "Uric acid"],
}

NUM = r"(\d{1,3}(?:\.\d+)?)"
BP_RE = re.compile(r"(?:혈압|BP)[^\d]{0,10}(\d{2,3})\s*/\s*(\d{2,3})")
BP_BARE_RE = re.compile(r"\b(1[0-9]{2}|[89][0-9])\s*/\s*([4-9][0-9]|1[0-2][0-9])\b")
DATE_RE = re.compile(r"(20\d{2})[-./년\s]{1,2}(\d{1,2})[-./월\s]{1,2}(\d{1,2})")
# \b는 한글 앞에서 매칭되지 않으므로("2025년") 숫자 경계로 판단
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def _alias_pattern(alias: str) -> re.Pattern:
    # 별칭 뒤 10자 이내의 첫 숫자를 그 항목의 수치로 본다 (콜론·공백·단위 허용)
    return re.compile(re.escape(alias) + r"[^\d\n/]{0,12}" + NUM)


def _to_number(raw: str) -> Any:
    f = float(raw)
    return int(f) if f.is_integer() else f


def parse_checkup_text(text: str) -> Dict[str, Any]:
    """자유 텍스트 → {relation, year, date, metrics}. 없는 값은 None/빈 dict."""
    result: Dict[str, Any] = {"relation": None, "year": None, "date": None, "metrics": {}}
    if not text:
        return result
    metrics: Dict[str, Any] = {}

    # 혈압 (명시 라벨 우선, 없으면 생리적 범위의 N/M 패턴)
    m = BP_RE.search(text) or BP_BARE_RE.search(text)
    if m:
        metrics["수축기혈압"] = _to_number(m.group(1))
        metrics["이완기혈압"] = _to_number(m.group(2))

    # 별칭 매칭 — 긴 별칭부터 시도, 이미 찾은 항목은 건너뜀
    for metric, aliases in METRIC_ALIASES.items():
        if metric in metrics:
            continue
        for alias in sorted(aliases, key=len, reverse=True):
            m = _alias_pattern(alias).search(text)
            if m:
                metrics[metric] = _to_number(m.group(1))
                break

    # 날짜·연도
    m = DATE_RE.search(text)
    if m:
        result["date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        result["year"] = int(m.group(1))
    else:
        m = YEAR_RE.search(text)
        if m:
            result["year"] = int(m.group(1))

    # 관계호칭 감지 (등록된 표준 호칭 단어)
    for rel in vault.KNOWN_RELATIONS:
        if re.search(rf"(?<![가-힣]){rel}(?![가-힣])", text):
            result["relation"] = rel
            break

    result["metrics"] = metrics
    return result


# ---------------------------------------------------------------- MD 파싱

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$", re.MULTILINE)


def _normalize_metric_name(name: str) -> Optional[str]:
    name = name.strip()
    for metric, aliases in METRIC_ALIASES.items():
        if name == metric or name in aliases:
            return metric
    return None


def parse_md_content(content: str) -> Dict[str, Any]:
    """md 내용 → {kind, data}.

    - kind="checkup"/"visit": 우리 노트 형식(frontmatter type) — data는 저장 가능한 구조
    - kind="parsed": 비정형 md — 표/본문에서 추출한 미리보기 (사용자 확인 필요)
    """
    m = FRONTMATTER_RE.match(content)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        note_type = meta.get("type")
        if note_type == "checkup" and meta.get("metrics"):
            return {"kind": "checkup", "data": {
                "relation": meta.get("member"),
                "year": meta.get("year"),
                "date": str(meta.get("date") or "") or None,
                "metrics": dict(meta["metrics"]),
            }}
        if note_type == "visit":
            return {"kind": "visit", "data": {
                "relation": meta.get("member"),
                "date": str(meta.get("date") or "") or None,
                "hospital": meta.get("hospital", ""),
                "symptoms": list(meta.get("symptoms") or []),
                "diagnosis": meta.get("diagnosis", ""),
                "medications": list(meta.get("medications") or []),
            }}
        if note_type in ("analysis", "profile", "family", "family_history"):
            # 파생/메타 노트 — 검진 데이터로 재입력하지 않음
            return {"kind": "other", "data": {"type": note_type}}
        # frontmatter는 있지만 다른 형식 → 본문 폴백
        content = content[m.end():]

    # 비정형: |항목|수치| 표 우선, 본문 텍스트 폴백
    parsed = parse_checkup_text(content)
    for name, value in TABLE_ROW_RE.findall(content):
        metric = _normalize_metric_name(name)
        if metric is None or metric in parsed["metrics"]:
            continue
        vm = re.search(NUM, value)
        if vm:
            parsed["metrics"][metric] = _to_number(vm.group(1))
    # 표에 혈압이 "120/80" 형태로 있는 경우
    for name, value in TABLE_ROW_RE.findall(content):
        if "혈압" in name and "/" in value:
            bm = re.search(r"(\d{2,3})\s*/\s*(\d{2,3})", value)
            if bm:
                parsed["metrics"].setdefault("수축기혈압", _to_number(bm.group(1)))
                parsed["metrics"].setdefault("이완기혈압", _to_number(bm.group(2)))
    return {"kind": "parsed", "data": parsed}
