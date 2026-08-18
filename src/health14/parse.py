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


# ------------------------------------------- 진료명세서·약국영수증 파싱

# 병원종류(진료과) — 기존 스키마의 hospital 필드에 저장한다.
# 특정 병원 상호는 저장하지 않는다(개인 동선 정보 최소화).
DEPARTMENTS = [
    "응급의학과", "가정의학과", "이비인후과", "정형외과", "신경외과", "성형외과",
    "산부인과", "비뇨의학과", "비뇨기과", "소아청소년과", "소아과", "정신건강의학과",
    "재활의학과", "영상의학과", "마취통증의학과", "흉부외과", "안과", "치과", "피부과",
    "내과", "외과", "한의원", "한방과", "응급실",
]
FACILITY_RE = re.compile(r"(약국|병원|의원|보건소|클리닉|한의원|치과)")

# 조제일자 2026-07-25 / 진료일: 2026.07.25 / 진료기간 2026-07-25 ~ ...
VISIT_DATE_RE = re.compile(
    r"(?:진료(?:일자|일|기간)|조제일자|조제일|처방일자|처방일|투약일)"
    r"[^\d]{0,6}(20\d{2})[-./년\s]{1,2}(\d{1,2})[-./월\s]{1,2}(\d{1,2})")

# 금액 라벨 → 표준 키 (쉼표 포함 숫자)
COST_LABELS = {
    "본인부담금": ["본인부담금", "본인부담액", "환자부담금", "본인 부담금"],
    "총액": ["총액", "진료비총액", "요양급여비용총액", "합계금액", "합계"],
    "납부금액": ["납부금액", "수납금액", "청구금액", "결제금액", "받은금액"],
    "공단부담금": ["공단부담금", "공단부담액", "보험자부담금"],
}
AMOUNT = r"[^\d\n]{0,8}([\d,]{3,})\s*원?"

# 약국영수증의 조제 목록: "1. 록소프로펜나트륨정 60mg  1일3회 3일분"
DRUG_LINE_RE = re.compile(
    r"^\s*\d+\s*[.)]\s*([가-힣A-Za-z][가-힣A-Za-z0-9\s()\-·]*?"
    r"(?:정|캡슐|시럽|현탁액|산|과립|환|연고|크림|액|주사|주|패치|점안액))"
    r"(?=\s|\d|$)", re.MULTILINE)
# 라벨형 처방약: "처방약: 록소프로펜, 알마겔"
DRUG_LABEL_RE = re.compile(r"(?:처방약|처방\s*의약품|투약내역|조제약)\s*[:：]\s*([^\n]+)")


def _to_won(raw: str) -> Optional[int]:
    digits = raw.replace(",", "").strip()
    return int(digits) if digits.isdigit() else None


def detect_document_type(text: str) -> str:
    """OCR 텍스트가 어떤 문서인지 판별.

    반환: "checkup"(검진결과지) | "pharmacy"(약국영수증)
          | "statement"(진료비 명세서·영수증) | "unknown"
    """
    if not text:
        return "unknown"
    pharmacy = sum(k in text for k in
                   ("약국", "조제", "복약", "처방전", "일분", "1일", "조제일자"))
    statement = sum(k in text for k in
                    ("진료비", "계산서", "본인부담", "공단부담", "진찰료", "급여",
                     "수납", "진료과", "외래", "입원"))
    checkup = len(parse_checkup_text(text)["metrics"])
    if "건강검진" in text or "검진결과" in text:
        checkup += 2

    scores = {"pharmacy": pharmacy, "statement": statement, "checkup": checkup}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 2 else "unknown"


def parse_visit_text(text: str) -> Dict[str, Any]:
    """진료명세서·약국영수증 텍스트 → 진료 기록 구조.

    반환 {relation, date, hospital, medications, cost, doc_type}.
    병원 상호·환자 식별정보는 추출하지 않는다(익명화는 저장 단계에서 별도 수행).
    """
    result: Dict[str, Any] = {
        "relation": None, "date": None, "hospital": "",
        "medications": [], "cost": {}, "doc_type": detect_document_type(text),
    }
    if not text:
        return result

    # 날짜 — 라벨이 붙은 진료일/조제일 우선, 없으면 본문 첫 날짜
    m = VISIT_DATE_RE.search(text) or DATE_RE.search(text)
    if m:
        result["date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # 병원종류: 진료과명이 있으면 그것, 없으면 시설 종류(약국/병원 등)
    for dept in DEPARTMENTS:
        if dept in text:
            result["hospital"] = dept
            break
    else:
        f = FACILITY_RE.search(text)
        if f:
            result["hospital"] = f.group(1)

    # 처방약
    meds: List[str] = []
    for name in DRUG_LINE_RE.findall(text):
        name = re.sub(r"\s{2,}", " ", name).strip()
        if name and name not in meds:
            meds.append(name)
    for chunk in DRUG_LABEL_RE.findall(text):
        for name in re.split(r"[,·/]", chunk):
            name = name.strip()
            if name and name not in meds:
                meds.append(name)
    result["medications"] = meds

    # 금액
    cost: Dict[str, int] = {}
    for key, labels in COST_LABELS.items():
        for label in labels:
            m = re.search(re.escape(label) + AMOUNT, text)
            if m:
                won = _to_won(m.group(1))
                if won is not None:
                    cost[key] = won
                break
    result["cost"] = cost

    # 관계호칭 감지
    for rel in vault.KNOWN_RELATIONS:
        if re.search(rf"(?<![가-힣]){rel}(?![가-힣])", text):
            result["relation"] = rel
            break
    return result


def extract_patient_name(text: str) -> Optional[str]:
    """영수증·명세서에서 환자 실명을 뽑는다 (자동매칭 전용, 저장하지 않음)."""
    if not text:
        return None
    m = re.search(
        r"(?:환자\s*명|수진자\s*명?|성\s*명|이\s*름|환자)\s*[:：]?\s*([가-힣]{2,4})(?![가-힣])",
        text)
    if m:
        return m.group(1)
    m = re.search(r"([가-힣]{2,4})\s*(?:님|씨)", text)
    return m.group(1) if m else None


def match_member(text: str, aliases: Optional[Dict[str, str]] = None,
                 known_relations: Optional[List[str]] = None) -> Dict[str, Any]:
    """영수증 원문에서 어느 가족의 것인지 찾아낸다.

    **반드시 익명화 이전의 원문**에 적용해야 한다(익명화하면 실명이 사라짐).
    반환 {relation, matched_by, name} — 못 찾으면 relation=None.
    실명(name)은 화면에서 확인만 시키고 저장하지 않는다.

    known_relations: vault에 실제 등록된 구성원 관계호칭. 주면 그 목록만 대조한다.
    matched_by: "실명" | "관계호칭"
    """
    result: Dict[str, Any] = {"relation": None, "matched_by": None, "name": None}
    if not text:
        return result
    candidates = known_relations if known_relations is not None else vault.KNOWN_RELATIONS

    # 1순위: 등록된 실명이 문서에 나타나면 그 구성원 (긴 이름부터)
    for name in sorted(aliases or {}, key=len, reverse=True):
        if name and name in text:
            return {"relation": aliases[name], "matched_by": "실명", "name": name}

    # 2순위: 환자명 라벨의 값이 관계호칭 자체인 경우 ("환자명: 아들")
    patient = extract_patient_name(text)
    if patient and patient in candidates:
        return {"relation": patient, "matched_by": "관계호칭", "name": patient}

    # 3순위: 본문에 등록된 관계호칭이 낱말 단위로 등장 (긴 호칭 우선)
    # 단순 부분일치를 쓰면 "나" 가 "나트륨"·"하나"에 걸려 오매칭된다.
    for rel in sorted(candidates, key=len, reverse=True):
        if rel and re.search(rf"(?<![가-힣]){re.escape(rel)}(?![가-힣])", text):
            return {"relation": rel, "matched_by": "관계호칭", "name": rel}
    return result


def parse_document(text: str) -> Dict[str, Any]:
    """문서 종류를 판별해 알맞은 파서 결과를 돌려준다.

    반환 {doc_type, kind: "checkup"|"visit", data} — kind가 프리필할 폼을 정한다.
    """
    doc_type = detect_document_type(text)
    if doc_type in ("pharmacy", "statement"):
        return {"doc_type": doc_type, "kind": "visit", "data": parse_visit_text(text)}
    return {"doc_type": doc_type, "kind": "checkup", "data": parse_checkup_text(text)}


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
