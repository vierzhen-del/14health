"""로컬 웹앱 API 검증 — 최초실행 플로우, 데이터 입력, 파일 접근 제한."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from health14 import webapp


@pytest.fixture
def server(isolated_config):
    srv = webapp.make_server(port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    port = srv.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()
        thread.join(timeout=2)


def _get(base, path):
    with urllib.request.urlopen(base + path) as r:
        return json.loads(r.read())


def _post(base, path, data=None):
    req = urllib.request.Request(
        base + path, data=json.dumps(data or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _post_expect_error(base, path, data, status):
    req = urllib.request.Request(
        base + path, data=json.dumps(data or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req)
        assert False, "expected HTTPError"
    except urllib.error.HTTPError as e:
        assert e.code == status
        return json.loads(e.read())


def test_index_serves_html(server):
    with urllib.request.urlopen(server + "/") as r:
        body = r.read().decode("utf-8")
    assert "<title>14health</title>" in body


def test_first_run_state_has_no_vault(server):
    state = _get(server, "/api/state")
    assert state["hasVault"] is False
    assert state["suggestedPath"]


def test_vault_create_then_persists_across_requests(server, tmp_path):
    new_path = tmp_path / "myvault"
    res = _post(server, "/api/vault/create", {"path": str(new_path)})
    assert res["hasVault"] is True
    assert res["vaultPath"] == str(new_path.resolve())

    # 재요청(=앱 재실행 시뮬레이션) 시 setup 화면으로 되돌아가지 않아야 함
    state2 = _get(server, "/api/state")
    assert state2["hasVault"] is True
    assert state2["vaultPath"] == str(new_path.resolve())

    # 같은 경로로 다시 create를 호출해도 기존 파일을 덮어쓰지 않음(멱등)
    from health14 import vault
    members_before = vault.load_members(new_path)
    _post(server, "/api/vault/create", {"path": str(new_path)})
    assert vault.load_members(new_path) == members_before


def test_member_and_checkup_flow(server, tmp_path):
    new_path = tmp_path / "v2"
    _post(server, "/api/vault/create", {"path": str(new_path)})
    _post(server, "/api/member", {"relation": "나", "birth": 1978, "sex": "M"})

    res = _post(server, "/api/note", {
        "relation": "나", "type": "checkup", "year": 2025,
        "metrics": {"혈압": "120/80", "체중": 72},
    })
    assert res["ok"] is True

    data = _get(server, "/api/data")
    m = data["members"][0]
    assert m["relation"] == "나"
    assert m["latest"]["수축기혈압"]["value"] == 120
    assert m["latest"]["체중"]["value"] == 72


def test_data_payload_includes_vault_path(server, tmp_path):
    new_path = tmp_path / "vp"
    _post(server, "/api/vault/create", {"path": str(new_path)})
    data = _get(server, "/api/data")
    assert data["vaultPath"] == str(new_path.resolve())


def test_visit_and_history_flow(server, tmp_path):
    new_path = tmp_path / "v3"
    _post(server, "/api/vault/create", {"path": str(new_path)})
    _post(server, "/api/member", {"relation": "딸", "birth": 2012, "sex": "F"})
    res = _post(server, "/api/note", {
        "relation": "딸", "type": "visit", "date": "2026-06-20",
        "hospital": "소아과", "symptoms": ["기침", "발열"], "diagnosis": "감기",
    })
    assert res["ok"] is True

    hres = _post(server, "/api/history", {"relation": "부", "disease": "고혈압"})
    assert hres["ok"] is True

    data = _get(server, "/api/data")
    assert data["familyHistory"][0]["disease"] == "고혈압"


def test_note_without_vault_returns_409(server):
    err = _post_expect_error(server, "/api/note",
                             {"relation": "나", "type": "checkup", "year": 2025}, 409)
    assert "vault" in err["error"]


def test_analyze_and_dashboard_export(server, tmp_path):
    new_path = tmp_path / "v4"
    _post(server, "/api/vault/create", {"path": str(new_path)})
    _post(server, "/api/member", {"relation": "나", "birth": 1978, "sex": "M"})
    _post(server, "/api/note", {"relation": "나", "type": "checkup", "year": 2025,
                                "metrics": {"혈압": "138/88"}})
    res = _post(server, "/api/analyze", {"relation": "나"})
    assert "opinion" in res

    dres = _post(server, "/api/dashboard/export")
    assert dres["ok"] is True
    with urllib.request.urlopen(server + dres["url"]) as r:
        html = r.read().decode("utf-8")
    assert "가족 건강 현황" in html


def test_file_traversal_blocked(server, tmp_path):
    new_path = tmp_path / "v5"
    _post(server, "/api/vault/create", {"path": str(new_path)})
    try:
        urllib.request.urlopen(server + "/api/file?path=../../../etc/passwd")
        assert False, "expected HTTPError"
    except urllib.error.HTTPError as e:
        assert e.code == 403


def test_parse_text_endpoint(server, tmp_path):
    _post(server, "/api/vault/create", {"path": str(tmp_path / "pt")})
    r = _post(server, "/api/parse-text",
              {"text": "나 2025년 혈압 138/88 체중 80"})
    p = r["parsed"]
    assert p["relation"] == "나" and p["year"] == 2025
    assert p["metrics"]["수축기혈압"] == 138


def test_md_parse_and_import_endpoints(server, tmp_path):
    _post(server, "/api/vault/create", {"path": str(tmp_path / "mdp")})
    _post(server, "/api/member", {"relation": "나", "birth": 1978, "sex": "M"})
    content = ("---\ntype: checkup\nmember: 나\nyear: 2024\n"
               "metrics:\n  체중: 78\n---\n\n# 검진\n")
    preview = _post(server, "/api/md/parse", {"content": content})
    assert preview["saved"] is False and preview["kind"] == "checkup"

    result = _post(server, "/api/md/import", {"content": content})
    assert result["saved"] is True

    data = _get(server, "/api/data")
    assert data["members"][0]["latest"]["체중"]["value"] == 78


def test_md_export_endpoint(server, tmp_path):
    _post(server, "/api/vault/create", {"path": str(tmp_path / "mdx")})
    _post(server, "/api/member", {"relation": "나", "birth": 1978, "sex": "M"})
    _post(server, "/api/note", {"relation": "나", "type": "checkup", "year": 2025,
                                "metrics": {"체중": 80}})
    r = _post(server, "/api/md/export", {"relation": "나"})
    assert r["ok"] and len(r["files"]) >= 1
    with urllib.request.urlopen(server + r["files"][0]["url"]) as resp:
        assert "체중" in resp.read().decode("utf-8")


def test_ocr_endpoint_guides_when_unavailable(server, tmp_path):
    from health14 import ocr as ocr_mod
    _post(server, "/api/vault/create", {"path": str(tmp_path / "ocr")})
    if ocr_mod.tesseract_available():
        import pytest
        pytest.skip("tesseract 설치됨 — 미설치 안내 테스트는 해당 없음")
    err = _post_expect_error(server, "/api/ocr", {"folder": str(tmp_path)}, 422)
    assert "tesseract" in err["error"]


def test_export_and_share_file_download(server, tmp_path):
    new_path = tmp_path / "v6"
    _post(server, "/api/vault/create", {"path": str(new_path)})
    _post(server, "/api/member", {"relation": "나", "birth": 1978, "sex": "M"})
    _post(server, "/api/note", {"relation": "나", "type": "checkup", "year": 2025,
                                "metrics": {"체중": 72}})
    res = _post(server, "/api/export")
    assert res["url"].startswith("/api/file?path=")
    with urllib.request.urlopen(server + res["url"]) as r:
        assert len(r.read()) > 0


def test_ocr_endpoint_returns_matched_member(server, tmp_path, monkeypatch):
    """영수증 OCR 응답에 자동매칭 결과가 담긴다 (OCR은 스텁으로 대체)."""
    from health14 import config as config_mod
    from health14 import ocr as ocr_mod
    from health14 import webapp as webapp_mod

    _post(server, "/api/vault/create", {"path": str(tmp_path / "match")})
    _post(server, "/api/member", {"relation": "아들", "birth": 2012, "sex": "M"})
    config_mod.add_alias("홍철수", "아들")

    receipt = ("환자명: 홍철수  등록번호: 20240915\n조제일자 2026-07-25\n"
               "처방 의료기관: 소아청소년과\n1. 알마겔현탁액 1일3회\n본인부담금 4,800원")
    monkeypatch.setattr(ocr_mod, "tesseract_available", lambda: True)
    monkeypatch.setattr(webapp_mod.ocr, "tesseract_available", lambda: True)
    monkeypatch.setattr(webapp_mod.ocr, "extract_text",
                        lambda p: [{"file": "receipt.png", "text": receipt}])

    r = _post(server, "/api/ocr", {"folder": str(tmp_path)})
    item = r["results"][0]
    assert item["matchedMember"] == "아들"
    assert item["matchedBy"] == "실명"
    assert item["kind"] == "visit"
    # 응답 텍스트에는 실명·등록번호가 남지 않는다
    assert "홍철수" not in item["text"] and "20240915" not in item["text"]
    assert item["parsed"]["relation"] == "아들"
