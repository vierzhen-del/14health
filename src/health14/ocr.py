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


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


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
        proc = subprocess.run(
            ["tesseract", str(f), "stdout", "-l", lang],
            capture_output=True, text=True)
        results.append({"file": str(f), "text": proc.stdout.strip()})
    return results
