"""공단·심평원에서 **사용자가 직접 내려받은** 공식 파일 가져오기.

마이헬스웨이 API는 이용기관 사전심사 대상이라 개인 앱이 쓸 수 없고, 공공데이터포털의
건강검진 데이터셋은 표본 통계일 뿐 본인 결과가 아니다(`docs/아키텍처.md`).
그래서 **인증은 사용자가 공단 사이트에서 직접 하고, 내려받은 파일만 앱에 넣는 방식**을
쓴다. 인증정보(간편인증·공동인증서)가 앱을 거치지 않는 것이 이 방식의 핵심 이점이다.

PDF는 `pdftotext`(poppler-utils)가 있으면 텍스트를 뽑고, 없으면 설치 안내를 낸다
(tesseract와 같은 선택적 의존 패턴).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from health14 import parse

TEXT_EXTS = {".txt", ".csv", ".md"}
PDF_EXTS = {".pdf"}

# 공식 서식에서만 나타나는 표현 — 일반 영수증과 구분한다
OFFICIAL_MARKERS = (
    "국민건강보험공단", "건강보험공단", "건강검진 결과 통보서", "건강검진결과통보서",
    "일반건강검진", "생애전환기", "나의 건강기록", "진료받은 내용", "투약내역",
    "건강보험심사평가원", "요양급여",
)


def pdftotext_available() -> bool:
    return shutil.which("pdftotext") is not None


def extract_text(path: Path) -> str:
    """파일에서 텍스트를 뽑는다. 지원하지 않는 형식이면 SystemExit."""
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTS:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix in PDF_EXTS:
        if not pdftotext_available():
            raise SystemExit(
                "PDF를 읽으려면 pdftotext가 필요합니다.\n"
                "  - Ubuntu/Termux(proot): apt install poppler-utils\n"
                "  - macOS: brew install poppler\n"
                "  - Windows: poppler 배포판 설치 후 PATH 등록\n"
                "또는 PDF를 캡쳐해 입력 탭의 '사진' 방식으로 넣으세요.")
        proc = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f"PDF 텍스트 추출 실패: {proc.stderr.strip()}")
        return proc.stdout
    raise SystemExit(f"지원하지 않는 형식입니다: {path.suffix} (pdf/txt/csv/md)")


def is_official(text: str) -> bool:
    return sum(m in text for m in OFFICIAL_MARKERS) >= 1


# 공식 검진 통보서는 "항목  결과  참고치" 형태의 줄이 많다
RESULT_ROW_RE = re.compile(
    r"^\s*([가-힣A-Za-z][가-힣A-Za-z0-9()\-/ ]{1,20}?)\s{2,}"
    r"(\d{1,3}(?:\.\d+)?)\s", re.MULTILINE)


def parse_official(text: str) -> Dict[str, Any]:
    """공식 파일 → parse_document()와 같은 모양의 결과.

    반환 {doc_type, kind, data} — doc_type은 official_checkup | official_visit.
    """
    lowered = text
    visit_hits = sum(k in lowered for k in
                     ("진료받은 내용", "투약내역", "처방", "요양기관", "내원일수"))
    checkup_hits = sum(k in lowered for k in
                       ("건강검진", "검진결과", "판정", "참고치", "계측검사"))

    if visit_hits > checkup_hits:
        data = parse.parse_visit_text(text)
        return {"doc_type": "official_visit", "kind": "visit", "data": data}

    data = parse.parse_checkup_text(text)
    # 표 형태의 "항목  값" 줄에서 놓친 수치를 보완
    for name, value in RESULT_ROW_RE.findall(text):
        metric = parse._normalize_metric_name(name.strip())
        if metric and metric not in data["metrics"]:
            data["metrics"][metric] = parse._to_number(value)
    return {"doc_type": "official_checkup", "kind": "checkup", "data": data}


def parse_file(path: Path) -> Dict[str, Any]:
    """공식 파일 하나를 읽어 파싱한다. 공식 서식이 아니면 일반 파서로 넘긴다."""
    text = extract_text(path)
    result = parse_official(text) if is_official(text) else parse.parse_document(text)
    result["text"] = text
    result["file"] = str(path)
    return result


def parse_path(target: Path) -> List[Dict[str, Any]]:
    """파일 또는 폴더를 파싱한다."""
    if target.is_dir():
        files = sorted(f for f in target.iterdir()
                       if f.suffix.lower() in TEXT_EXTS | PDF_EXTS)
    else:
        files = [target]
    if not files:
        raise SystemExit(f"읽을 수 있는 파일이 없습니다: {target}")
    return [parse_file(f) for f in files]
