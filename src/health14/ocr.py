"""선택적 로컬 OCR (tesseract). 미설치 시 안내만 하고 종료.

이미지 분석의 기본 경로는 Claude Code / Gemini CLI 스킬이며,
이 모듈은 AI 없이 CLI만 쓸 때의 보조 수단이다. 모든 처리는 로컬에서 수행된다.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"}

# 검진지·영수증은 표 형태라 psm 6(균일한 텍스트 블록)이 기본값 3보다 훨씬 정확하다.
# 실측: 명세서 이미지에서 psm 3은 글자가 깨졌고 psm 6은 전 줄을 정확히 읽었다.
# 레이아웃이 특이한 문서를 대비해 4(단일 컬럼)·3(자동)을 차례로 시도하고
# 가장 잘 읽힌 결과를 고른다.
PSM_ORDER = ("6", "4", "3")


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _score(text: str) -> int:
    """읽기 품질 점수 — 한글·숫자 글자 수. 깨진 결과일수록 낮다."""
    return sum(1 for ch in text if "가" <= ch <= "힣" or ch.isdigit())


def extract_text(target: Path) -> List[dict]:
    """이미지 파일 또는 폴더에서 텍스트 추출 → [{file, text}]."""
    if not tesseract_available():
        raise SystemExit(
            "tesseract가 설치되어 있지 않습니다.\n"
            "  - macOS: brew install tesseract tesseract-lang\n"
            "  - Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-kor\n"
            "  - Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "또는 Claude Code / Gemini CLI 스킬로 이미지 분석을 사용하세요.")
    files: List[Path] = []
    if target.is_dir():
        files = sorted(p for p in target.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    elif target.suffix.lower() in IMAGE_EXTS:
        files = [target]
    if not files:
        raise SystemExit(f"이미지 파일이 없습니다: {target}")

    # 한국어 데이터가 있으면 kor+eng, 없으면 eng
    langs = subprocess.run(["tesseract", "--list-langs"],
                           capture_output=True, text=True).stdout
    lang = "kor+eng" if "kor" in langs else "eng"

    results = []
    for f in files:
        best, best_score = "", -1
        for psm in PSM_ORDER:
            proc = subprocess.run(
                ["tesseract", str(f), "stdout", "-l", lang, "--psm", psm],
                capture_output=True, text=True)
            text = proc.stdout.strip()
            score = _score(text)
            if score > best_score:
                best, best_score = text, score
            # 충분히 잘 읽혔으면 나머지 모드는 시도하지 않는다 (속도)
            if score >= 60:
                break
        results.append({"file": str(f), "text": best})
    return results
