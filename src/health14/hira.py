"""건강보험심사평가원(HIRA) 공개 API — 병원·약국 찾기.

data.go.kr 에서 발급받은 서비스키로 전국 병의원·약국 현황을 조회한다.
3가지 외부 API 후보 중 **개인 개발자가 즉시 쓸 수 있는 유일한 경로**다
(마이헬스웨이는 이용기관 사전심사 대상, NHIS 개인 검진결과는 공개 API 없음 —
`docs/아키텍처.md` 참조).

## 개인정보 원칙

이 모듈이 외부로 보내는 값은 **지역·진료과·검색어뿐**이다. 가족 구성원의 이름·
수치·병명·진단은 어떤 경우에도 쿼리에 담지 않는다. `search()` 는 화이트리스트된
파라미터만 조립하므로 구조적으로 다른 값이 섞일 수 없고, 이를 테스트가 고정한다.

키가 없으면 기능만 비활성되고 앱은 정상 동작한다.
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from health14 import config

BASE = "https://apis.data.go.kr/B551182"
HOSPITAL_PATH = "/hospInfoServicev2/getHospBasisList"
PHARMACY_PATH = "/pharmacyInfoService/getParmacyBasisList"

# 쿼리에 실을 수 있는 파라미터 — 이 목록 밖은 전송되지 않는다
ALLOWED_PARAMS = {
    "sidoCd", "sgguCd", "yadmNm", "dgsbjtCd", "zipCd", "clCd",
    "pageNo", "numOfRows",
}

# 진료과 → 심평원 진료과목 코드 (자주 쓰는 것만)
DEPARTMENT_CODES = {
    "내과": "01", "소아과": "10", "소아청소년과": "10", "외과": "04",
    "정형외과": "05", "신경외과": "06", "산부인과": "11", "안과": "12",
    "이비인후과": "13", "피부과": "14", "비뇨의학과": "15", "비뇨기과": "15",
    "정신건강의학과": "08", "재활의학과": "21", "가정의학과": "23",
    "응급의학과": "24", "치과": "49", "한의원": "80",
}

TIMEOUT = 10


class HiraError(RuntimeError):
    """조회 실패 — 호출부에서 안내 문구로 바꿔 보여준다."""


def api_key() -> Optional[str]:
    return config.load_config().get("hira_key") or None


def available() -> bool:
    return bool(api_key())


def department_code(name: str) -> Optional[str]:
    return DEPARTMENT_CODES.get((name or "").strip())


def _get(path: str, params: Dict[str, Any]) -> List[Dict[str, str]]:
    key = api_key()
    if not key:
        raise HiraError(
            "심평원 API 키가 설정되지 않았습니다. "
            "data.go.kr 에서 '병원정보서비스' 활용신청 후 "
            "`14health config set hira_key <키>` 로 등록하세요.")

    # 화이트리스트 밖의 값은 버린다 — 건강정보가 실릴 여지를 없앤다
    safe = {k: v for k, v in params.items()
            if k in ALLOWED_PARAMS and v not in (None, "")}
    safe.setdefault("numOfRows", 20)
    safe.setdefault("pageNo", 1)

    query = urllib.parse.urlencode(safe, encoding="utf-8")
    url = f"{BASE}{path}?serviceKey={urllib.parse.quote(key, safe='')}&{query}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            body = resp.read()
    except (urllib.error.URLError, OSError) as e:
        raise HiraError(f"심평원 API 호출 실패: {e}") from e
    return _parse_items(body)


def _parse_items(body: bytes) -> List[Dict[str, str]]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise HiraError(f"응답을 해석할 수 없습니다: {e}") from e

    code = root.findtext(".//resultCode")
    if code not in (None, "00"):
        msg = root.findtext(".//resultMsg") or "알 수 없는 오류"
        raise HiraError(f"심평원 API 오류({code}): {msg}")

    items = []
    for item in root.iter("item"):
        items.append({child.tag: (child.text or "").strip() for child in item})
    return items


def _normalize(raw: Dict[str, str]) -> Dict[str, str]:
    return {
        "이름": raw.get("yadmNm", ""),
        "주소": raw.get("addr", ""),
        "전화": raw.get("telno", ""),
        "종별": raw.get("clCdNm", ""),
        "홈페이지": raw.get("hospUrl", ""),
    }


def search_hospital(sido: str = "", sggu: str = "", department: str = "",
                    name: str = "") -> List[Dict[str, str]]:
    """병의원 검색. 지역·진료과·상호만 전송한다."""
    return [_normalize(x) for x in _get(HOSPITAL_PATH, {
        "sidoCd": sido, "sgguCd": sggu,
        "dgsbjtCd": department_code(department),
        "yadmNm": name,
    })]


def search_pharmacy(sido: str = "", sggu: str = "",
                    name: str = "") -> List[Dict[str, str]]:
    """약국 검색."""
    return [_normalize(x) for x in _get(PHARMACY_PATH, {
        "sidoCd": sido, "sgguCd": sggu, "yadmNm": name,
    })]
