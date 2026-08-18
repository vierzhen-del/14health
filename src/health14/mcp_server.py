"""14health MCP 서버 (stdio) — Claude CLI · n8n 등에서 도구로 호출.

Tab S9 등록:
    claude mcp add 14health -- 14health mcp

외부 의존성 없이 JSON-RPC 2.0 over stdio 를 직접 구현한다(표준 라이브러리만).
모든 도구는 로컬 vault만 읽고 쓰며, 인터넷으로 나가는 것은 병원 검색(HIRA)뿐이다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

from health14 import (analysis, calendar_index, config, hira, insurance,
                      intake, recommend, relations, vault)

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "14health", "version": "0.1.0"}


def _vault() -> Path:
    v = config.get_vault_path(required=False)
    if v is None or not v.exists():
        raise RuntimeError(
            "vault가 설정되지 않았습니다. `14health init --vault <경로>` 를 먼저 실행하세요.")
    return v


# ---------------------------------------------------------------- 도구 구현

def _list_members(_: Dict[str, Any]) -> Any:
    v = _vault()
    return [{
        "관계호칭": m["relation"],
        "표시명": relations.display_name(m),
        "분류": relations.member_category(m),
        "나이": vault.age_of(m),
        "성별": m.get("sex", ""),
    } for m in vault.load_members(v)]


def _member_summary(args: Dict[str, Any]) -> Any:
    v = _vault()
    report = analysis.build_member_report(v, args["relation"])
    return {
        "표시명": report["relation"], "나이": report["age"], "생애주기": report["stage"],
        "최근수치": {k: {"값": d.get("value"), "단위": d.get("unit", ""),
                        "판정": d.get("status")} for k, d in report["latest"].items()},
        "위험요인": report["risks"],
        "추이": report["trends"],
        "종합소견": report["opinion"],
    }


def _recommend(args: Dict[str, Any]) -> Any:
    v = _vault()
    targets = ([args["relation"]] if args.get("relation")
               else [m["relation"] for m in vault.load_members(v)])
    out = []
    for relation in targets:
        r = analysis.build_member_report(v, relation)
        out.append({
            "대상": relation, "나이": r["age"], "생애주기": r["stage"],
            "권장검진": r["recommendations"], "권장진료": r["departments"],
            "생활습관": r["lifestyle"], "분기계획": r["quarters"],
            "종합소견": r["opinion"],
        })
    return {"엔진": "규칙 기반(오프라인)", "결과": out}


def _add_visit(args: Dict[str, Any]) -> Any:
    v = _vault()
    path = intake.apply_visit(v, args["relation"], {
        "date": args["date"], "hospital": args.get("hospital", "진료"),
        "symptoms": args.get("symptoms", []),
        "diagnosis": args.get("diagnosis", ""),
        "medications": args.get("medications", []),
        "cost": args.get("cost") or {},
        "claim": args.get("claim"),
        "memo": args.get("memo", ""),
    })
    return {"저장됨": str(path)}


def _add_checkup(args: Dict[str, Any]) -> Any:
    v = _vault()
    path = intake.apply_checkup(v, args["relation"], {
        "year": args["year"], "date": args.get("date"),
        "metrics": args.get("metrics") or {}, "memo": args.get("memo", ""),
    })
    return {"저장됨": str(path)}


def _calendar(args: Dict[str, Any]) -> Any:
    v = _vault()
    year = args.get("year")
    return calendar_index.build_index(v, int(year) if year else None)


def _pending_claims(_: Dict[str, Any]) -> Any:
    v = _vault()
    return {"요약": insurance.claim_summary(v),
            "목록": insurance.pending_claims(v)}


def _find_hospital(args: Dict[str, Any]) -> Any:
    if not hira.available():
        return {"안내": "심평원 API 키가 없습니다. "
                        "`14health config set hira_key <키>` 로 등록하세요."}
    return hira.search_hospital(
        sido=args.get("sido", ""), sggu=args.get("sggu", ""),
        department=args.get("department", ""), name=args.get("name", ""))


def _family_tree(_: Dict[str, Any]) -> Any:
    return relations.build_family_tree(_vault())


TOOLS: List[Dict[str, Any]] = [
    {
        "name": "list_members",
        "description": "가족 구성원 목록(관계호칭·표시명·분류·나이)을 돌려준다.",
        "inputSchema": {"type": "object", "properties": {}},
        "_fn": _list_members,
    },
    {
        "name": "member_summary",
        "description": "한 구성원의 최근 검진 수치·판정·위험요인·추이·종합소견.",
        "inputSchema": {
            "type": "object",
            "properties": {"relation": {"type": "string", "description": "관계호칭"}},
            "required": ["relation"],
        },
        "_fn": _member_summary,
    },
    {
        "name": "recommend",
        "description": "예방 건강검진·생활습관·진료과 추천(규칙 기반, 오프라인). "
                       "relation 생략 시 가족 전원.",
        "inputSchema": {
            "type": "object",
            "properties": {"relation": {"type": "string"}},
        },
        "_fn": _recommend,
    },
    {
        "name": "add_visit",
        "description": "진료 기록을 옵시디안 vault에 저장한다(실명은 자동 익명화).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "relation": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "hospital": {"type": "string", "description": "병원종류·진료과"},
                "symptoms": {"type": "array", "items": {"type": "string"}},
                "diagnosis": {"type": "string"},
                "medications": {"type": "array", "items": {"type": "string"}},
                "cost": {"type": "object", "description": "예: {\"본인부담금\": 12000}"},
                "claim": {"type": "object", "description": "실비 청구 상태"},
                "memo": {"type": "string"},
            },
            "required": ["relation", "date"],
        },
        "_fn": _add_visit,
    },
    {
        "name": "add_checkup",
        "description": "건강검진 수치를 저장한다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "relation": {"type": "string"},
                "year": {"type": "integer"},
                "date": {"type": "string"},
                "metrics": {"type": "object"},
                "memo": {"type": "string"},
            },
            "required": ["relation", "year"],
        },
        "_fn": _add_checkup,
    },
    {
        "name": "calendar",
        "description": "검진·진료 기록을 날짜순으로 조회한다(연도 필터 가능).",
        "inputSchema": {
            "type": "object",
            "properties": {"year": {"type": "integer"}},
        },
        "_fn": _calendar,
    },
    {
        "name": "pending_claims",
        "description": "실손보험 미청구 진료 건과 소멸시효 임박 여부.",
        "inputSchema": {"type": "object", "properties": {}},
        "_fn": _pending_claims,
    },
    {
        "name": "find_hospital",
        "description": "심평원 공개 API로 병의원을 찾는다. "
                       "지역·진료과만 전송하며 건강정보는 보내지 않는다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sido": {"type": "string", "description": "시도 코드"},
                "sggu": {"type": "string", "description": "시군구 코드"},
                "department": {"type": "string", "description": "진료과명 (예: 소아청소년과)"},
                "name": {"type": "string", "description": "병원명 일부"},
            },
        },
        "_fn": _find_hospital,
    },
    {
        "name": "family_tree",
        "description": "세대별 가족 관계도와 구성원별 주요 병명.",
        "inputSchema": {"type": "object", "properties": {}},
        "_fn": _family_tree,
    },
]

_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    t["name"]: t["_fn"] for t in TOOLS
}


def tool_specs() -> List[Dict[str, Any]]:
    """MCP에 노출하는 도구 정의 (내부 `_fn` 제외)."""
    return [{k: v for k, v in t.items() if not k.startswith("_")} for t in TOOLS]


# ---------------------------------------------------------------- JSON-RPC

def handle(request: Dict[str, Any]) -> Dict[str, Any] | None:
    """요청 하나를 처리한다. 알림(notification)이면 None."""
    method = request.get("method")
    req_id = request.get("id")

    if method == "initialize":
        result: Any = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    elif method == "tools/list":
        result = {"tools": tool_specs()}
    elif method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        fn = _HANDLERS.get(name)
        if fn is None:
            return _error(req_id, -32602, f"알 수 없는 도구: {name}")
        try:
            payload = fn(params.get("arguments") or {})
            text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
            result = {"content": [{"type": "text", "text": text}]}
        # SystemExit은 Exception이 아니라 BaseException이다. 이 코드베이스는
        # 사용자 오류를 SystemExit으로 알리므로 함께 잡지 않으면 서버가 죽는다.
        except (Exception, SystemExit) as e:
            result = {"content": [{"type": "text", "text": f"오류: {e}"}],
                      "isError": True}
    elif method in ("notifications/initialized", "initialized"):
        return None
    elif method == "ping":
        result = {}
    else:
        if req_id is None:
            return None
        return _error(req_id, -32601, f"지원하지 않는 메서드: {method}")

    if req_id is None:
        return None
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def serve(stdin=None, stdout=None) -> int:
    """stdio에서 JSON-RPC 메시지를 한 줄씩 읽어 처리한다."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
