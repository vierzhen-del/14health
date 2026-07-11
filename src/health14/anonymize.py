"""실명·개인식별정보 익명화.

vault에 저장되기 전의 모든 자유 텍스트는 이 모듈을 거친다.
- config에 등록된 실명(aliases)은 관계호칭으로 치환
- 주민등록번호·전화번호는 마스킹
- "OOO님/씨/환자" 꼴의 호칭 앞 이름은 [가족] 으로 치환
"""
from __future__ import annotations

import re
from typing import Dict, Optional

from health14 import config

RRN_RE = re.compile(r"\b\d{6}\s*-\s*[1-4]\d{6}\b")
PHONE_RE = re.compile(r"\b01[016789][-\s]?\d{3,4}[-\s]?\d{4}\b")
NAME_HONORIFIC_RE = re.compile(r"[가-힣]{2,4}(?=\s*(님|씨| 환자|환자분))")
# 숫자+단위 (혈압 120/80, 95 mg/dL, 72kg 등) — 노션 등 외부 전송용 마스킹
MEASUREMENT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:/\s*\d+(?:\.\d+)?)?\s*"
    r"(?:mmHg|mg/dL|mg|kg|cm|%|bpm|U/L|g/dL|mL|IU)?",
)


def anonymize(text: str, aliases: Optional[Dict[str, str]] = None) -> str:
    """저장용 익명화: 등록 실명 → 관계호칭, 식별번호 마스킹."""
    if not text:
        return text
    if aliases is None:
        aliases = config.get_aliases()
    for name in sorted(aliases, key=len, reverse=True):
        text = text.replace(name, aliases[name])
    text = RRN_RE.sub("[주민번호]", text)
    text = PHONE_RE.sub("[전화번호]", text)

    def _mask_name(m: "re.Match") -> str:
        word = m.group(0)
        # 이미 관계호칭이면 그대로 둔다 (부인님, 어머니 환자 등)
        from health14.vault import KNOWN_RELATIONS
        if word in KNOWN_RELATIONS or word in aliases.values():
            return word
        return "[가족]"

    text = NAME_HONORIFIC_RE.sub(_mask_name, text)
    return text


def _strip_measurement(m: "re.Match") -> str:
    # 단위 없는 연도(19xx/20xx)만 유지 — 그 외 숫자는 모두 제거
    token = m.group(0).strip()
    if re.fullmatch(r"(19|20)\d{2}", token):
        return token
    return ""


def mask_for_external(text: str, aliases: Optional[Dict[str, str]] = None) -> str:
    """외부(노션) 전송용 마스킹: 익명화 + 수치 제거(연도는 유지)."""
    text = anonymize(text or "", aliases)
    text = MEASUREMENT_RE.sub(_strip_measurement, text)
    return re.sub(r"\s{2,}", " ", text).strip()
