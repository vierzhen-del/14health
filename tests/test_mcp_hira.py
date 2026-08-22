"""MCP 서버 · 심평원(HIRA) 클라이언트."""
import io
import json

import pytest

from health14 import config, hira, mcp_server, vault


# ---------------------------------------------------------------- MCP

def _call(method, params=None, req_id=1):
    return mcp_server.handle({"jsonrpc": "2.0", "id": req_id,
                              "method": method, "params": params or {}})


def test_initialize_reports_server_info():
    r = _call("initialize")
    assert r["result"]["serverInfo"]["name"] == "14health"
    assert r["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSION


def test_tools_list_exposes_schemas():
    tools = _call("tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"list_members", "recommend", "add_visit", "pending_claims",
            "find_hospital", "family_tree", "treatment",
            "consult_briefing"} <= names
    for t in tools:
        assert "description" in t and "inputSchema" in t
        # 내부 구현 참조가 새어나가면 안 된다
        assert not any(k.startswith("_") for k in t)


def test_notifications_return_nothing():
    assert mcp_server.handle({"jsonrpc": "2.0",
                              "method": "notifications/initialized"}) is None


def test_unknown_method_errors():
    r = _call("does/not/exist")
    assert r["error"]["code"] == -32601


def test_unknown_tool_errors():
    r = _call("tools/call", {"name": "nope", "arguments": {}})
    assert r["error"]["code"] == -32602


def test_tool_call_returns_member_list(vault_path):
    vault.add_member(vault_path, "나", 1978, "M", "본인")
    vault.add_member(vault_path, "아들(첫째)", 2010, "M", "자녀", "큰아들")
    r = _call("tools/call", {"name": "list_members", "arguments": {}})
    rows = json.loads(r["result"]["content"][0]["text"])
    assert {row["관계호칭"] for row in rows} == {"나", "아들(첫째)"}
    assert [row for row in rows if row["관계호칭"] == "아들(첫째)"][0]["표시명"] == "큰아들"


def test_tool_error_is_returned_not_raised(vault_path):
    """도구 실행 오류는 예외가 아니라 isError 결과로 돌려준다."""
    r = _call("tools/call", {"name": "member_summary",
                             "arguments": {"relation": "없는사람"}})
    assert r["result"]["isError"] is True
    assert "오류" in r["result"]["content"][0]["text"]


def test_add_visit_through_mcp(vault_path):
    vault.add_member(vault_path, "나", 1978, "M")
    r = _call("tools/call", {"name": "add_visit", "arguments": {
        "relation": "나", "date": "2026-03-14", "hospital": "내과",
        "symptoms": ["기침"], "diagnosis": "감기",
        "cost": {"본인부담금": 12000}}})
    assert "저장됨" in r["result"]["content"][0]["text"]
    assert vault.load_visits(vault_path, "나")[0]["hospital"] == "내과"


def test_serve_reads_stdio(vault_path):
    lines = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
    out = io.StringIO()
    mcp_server.serve(stdin=io.StringIO(lines), stdout=out)
    assert json.loads(out.getvalue())["result"]["serverInfo"]["name"] == "14health"


# ---------------------------------------------------------------- HIRA

def test_hira_disabled_without_key(vault_path):
    assert hira.available() is False
    with pytest.raises(hira.HiraError) as e:
        hira.search_hospital(department="내과")
    assert "hira_key" in str(e.value)


def test_department_code_lookup():
    assert hira.department_code("소아청소년과") == "10"
    assert hira.department_code("소아과") == "10"
    assert hira.department_code("없는과") is None


def test_query_only_carries_allowed_params(vault_path, monkeypatch):
    """건강정보가 쿼리에 섞여도 전송되지 않는다 (화이트리스트)."""
    captured = {}

    def fake_urlopen(url, timeout=None):
        captured["url"] = url
        raise OSError("네트워크 차단됨")

    config.save_config({"vault": str(vault_path), "hira_key": "TESTKEY"})
    monkeypatch.setattr(hira.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(hira.HiraError):
        hira._get(hira.HOSPITAL_PATH, {
            "sidoCd": "110000", "dgsbjtCd": "01",
            "환자명": "홍길동", "혈압": "138/88", "진단": "고혈압",
        })

    url = captured["url"]
    assert "sidoCd=110000" in url and "dgsbjtCd=01" in url
    for leaked in ("홍길동", "138", "고혈압", "환자명", "혈압", "진단"):
        assert leaked not in url, f"{leaked} 이 쿼리에 실렸다"


def test_parse_items_reports_api_error():
    body = ("<response><header><resultCode>99</resultCode>"
            "<resultMsg>서비스키 오류</resultMsg></header></response>").encode("utf-8")
    with pytest.raises(hira.HiraError) as e:
        hira._parse_items(body)
    assert "서비스키 오류" in str(e.value)


def test_parse_items_normalizes_rows():
    body = ("<response><header><resultCode>00</resultCode></header><body><items>"
            "<item><yadmNm>서울소아과</yadmNm><addr>서울시 강남구</addr>"
            "<telno>02-123-4567</telno><clCdNm>의원</clCdNm></item>"
            "</items></body></response>").encode("utf-8")
    rows = hira._parse_items(body)
    assert rows[0]["yadmNm"] == "서울소아과"
    normalized = hira._normalize(rows[0])
    assert normalized["이름"] == "서울소아과" and normalized["전화"] == "02-123-4567"


def test_consult_briefing_tool(vault_path):
    from health14 import treatment
    vault.add_member(vault_path, "나", 1970, "M")
    vault.add_checkup(vault_path, "나", 2025, {"수축기혈압": 142})
    treatment.add_item(vault_path, "나", "condition", {"name": "고혈압"})
    r = _call("tools/call", {"name": "consult_briefing",
                             "arguments": {"relation": "나"}})
    b = json.loads(r["result"]["content"][0]["text"])
    assert b["구성원"][0]["대상"] == "나"
    assert b["구성원"][0]["현재_치료중"][0]["질환"] == "고혈압"
    assert "의학적 진단이 아닙니다" in b["면책"]


def test_treatment_tool(vault_path):
    from health14 import treatment
    vault.add_member(vault_path, "나", 1970, "M")
    treatment.add_item(vault_path, "나", "medication", {"name": "암로디핀"})
    r = _call("tools/call", {"name": "treatment", "arguments": {}})
    data = json.loads(r["result"]["content"][0]["text"])
    assert data["나"]["medications"][0]["name"] == "암로디핀"


def test_consult_briefing_error_is_returned_not_raised(vault_path):
    """등록 안 된 구성원 → SystemExit 이 서버를 죽이지 않고 isError 로 온다."""
    r = _call("tools/call", {"name": "consult_briefing",
                             "arguments": {"relation": "없는사람"}})
    assert r["result"]["isError"] is True
