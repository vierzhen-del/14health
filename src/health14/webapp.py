"""14health 로컬 웹앱 — 표준 라이브러리만 사용하는 localhost 전용 서버.

브라우저에서 대시보드를 보고 데이터를 입력할 수 있는 GUI 셸이다.
127.0.0.1에만 바인딩되며 외부에서 접근할 수 없다. 최초 실행 시 vault가
없으면 생성 화면을 보여주고, 한 번 생성되면 config에 경로가 저장되어
이후에는 해당 화면이 다시 나타나지 않는다.
"""
from __future__ import annotations

import json
import mimetypes
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, quote, urlparse

from health14 import analysis, anonymize, config, dashboard, export, intake, share, vault


def _app_html() -> str:
    return (resources.files("health14")
            .joinpath("templates/app.html").read_text(encoding="utf-8"))


def _current_vault() -> Optional[Path]:
    p = config.get_vault_path(required=False)
    if p and p.exists():
        return p
    return None


def _state_payload() -> Dict[str, Any]:
    v = _current_vault()
    cfg = config.load_config()
    return {
        "hasVault": v is not None,
        "vaultPath": str(v) if v else (cfg.get("vault") or None),
        "suggestedPath": config.suggested_vault_path(),
    }


def _data_payload(v: Path) -> Dict[str, Any]:
    payload = dashboard.build_data(v)
    payload["vaultPath"] = str(v)
    payload["familyHistory"] = vault.load_family_history(v)
    payload["log"] = list(reversed(vault.load_log(v)[-20:]))
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = "14health/0.1"

    def log_message(self, fmt, *args):  # 콘솔 로그 최소화
        pass

    # ---------------------------------------------------------------- 응답 헬퍼

    def _send_json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _error(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status)

    def _require_vault(self) -> Optional[Path]:
        v = _current_vault()
        if v is None:
            self._error("vault가 설정되지 않았습니다.", 409)
            return None
        return v

    # ---------------------------------------------------------------- 라우팅

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                self._send_html(_app_html())
            elif path == "/api/state":
                self._send_json(_state_payload())
            elif path == "/api/data":
                v = self._require_vault()
                if v:
                    self._send_json(_data_payload(v))
            elif path == "/api/file":
                self._serve_file(parse_qs(parsed.query))
            else:
                self._error("Not Found", 404)
        except Exception as e:
            self._error(str(e), 500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            data = self._read_json()
            if path in ("/api/vault/create", "/api/vault/connect"):
                self._handle_vault_setup(data)
            elif path == "/api/member":
                self._handle_member(data)
            elif path == "/api/history":
                self._handle_history(data)
            elif path == "/api/note":
                self._handle_note(data)
            elif path == "/api/analyze":
                self._handle_analyze(data)
            elif path == "/api/dashboard/export":
                self._handle_dashboard_export()
            elif path == "/api/share":
                self._handle_share(data)
            elif path == "/api/export":
                self._handle_export()
            elif path == "/api/import":
                self._handle_import(data)
            else:
                self._error("Not Found", 404)
        except SystemExit as e:
            self._error(str(e))
        except Exception as e:
            self._error(str(e), 500)

    # ---------------------------------------------------------------- 핸들러

    def _handle_vault_setup(self, data: Dict[str, Any]) -> None:
        raw = (data.get("path") or "").strip()
        if not raw:
            return self._error("경로를 입력하세요.")
        path = Path(raw).expanduser()
        # init_vault는 없는 파일만 보완 생성 — 기존 vault를 재생성/덮어쓰기하지 않음
        vault.init_vault(path)
        config.set_vault_path(path)
        self._send_json(_state_payload())

    def _handle_member(self, data: Dict[str, Any]) -> None:
        v = self._require_vault()
        if not v:
            return
        relation = (data.get("relation") or "").strip()
        if not relation:
            return self._error("관계호칭을 입력하세요.")
        vault.add_member(v, relation, int(data["birth"]), data["sex"])
        self._send_json({"ok": True})

    def _handle_history(self, data: Dict[str, Any]) -> None:
        v = self._require_vault()
        if not v:
            return
        vault.add_family_history(v, data["relation"], data["disease"],
                                 anonymize.anonymize(data.get("note", "")))
        vault.log_action(v, "기타", "가족력입력", f"가족력 추가 ({data['relation']})",
                         v / vault.FAMILY_DIR / vault.HISTORY_FILE)
        self._send_json({"ok": True})

    def _handle_note(self, data: Dict[str, Any]) -> None:
        v = self._require_vault()
        if not v:
            return
        relation = data.get("relation")
        note_type = data.get("type")
        if not relation:
            return self._error("구성원을 선택하세요.")
        if note_type == "checkup":
            path = intake.apply_checkup(v, relation, data)
        elif note_type == "visit":
            path = intake.apply_visit(v, relation, data)
        else:
            return self._error("type은 checkup 또는 visit 이어야 합니다.")
        self._send_json({"ok": True, "path": str(path)})

    def _handle_analyze(self, data: Dict[str, Any]) -> None:
        v = self._require_vault()
        if not v:
            return
        relation = data["relation"]
        report = analysis.build_member_report(v, relation)
        path = analysis.write_analysis_note(v, relation, report)
        vault.log_action(v, relation, "위험분석", "위험도 분석 리포트 생성", path)
        self._send_json({"ok": True, "opinion": report["opinion"]})

    def _handle_dashboard_export(self) -> None:
        v = self._require_vault()
        if not v:
            return
        out = dashboard.generate(v)
        vault.log_action(v, "기타", "대시보드생성", "가족 건강 대시보드 갱신", out)
        self._send_json({"ok": True, "path": str(out),
                         "url": f"/api/file?path={quote('대시보드.html')}"})

    def _handle_share(self, data: Dict[str, Any]) -> None:
        v = self._require_vault()
        if not v:
            return
        out = share.make_share_card(v, data["relation"])
        vault.log_action(v, data["relation"], "공유이미지", "건강 요약 공유 이미지 생성")
        rel = out.relative_to(v).as_posix()
        self._send_json({"ok": True, "path": str(out), "url": f"/api/file?path={quote(rel)}"})

    def _handle_export(self) -> None:
        v = self._require_vault()
        if not v:
            return
        out = export.export_vault(v)
        vault.log_action(v, "기타", "내보내기", "vault 전체 내보내기(zip)")
        rel = out.relative_to(v).as_posix()
        self._send_json({"ok": True, "path": str(out), "url": f"/api/file?path={quote(rel)}"})

    def _handle_import(self, data: Dict[str, Any]) -> None:
        zip_path = Path(data["zipPath"]).expanduser()
        new_vault = Path(data["vaultPath"]).expanduser()
        new_v = export.import_vault(zip_path, new_vault, bool(data.get("overwrite")))
        vault.log_action(new_v, "기타", "가져오기", "vault 가져오기 완료")
        self._send_json(_state_payload())

    def _serve_file(self, query: Dict[str, Any]) -> None:
        v = _current_vault()
        if v is None:
            return self._error("vault가 설정되지 않았습니다.", 409)
        rel = (query.get("path") or [""])[0]
        if not rel:
            return self._error("path 파라미터가 필요합니다.")
        vault_resolved = v.resolve()
        target = (vault_resolved / rel).resolve()
        allowed_root = vault_resolved / vault.EXPORT_DIR
        is_dashboard = target == (vault_resolved / "대시보드.html")
        allowed = is_dashboard or (
            target.is_relative_to(allowed_root) if hasattr(target, "is_relative_to")
            else str(target).startswith(str(allowed_root))
        )
        if not allowed or not target.exists() or not target.is_file():
            return self._error("접근할 수 없는 경로입니다.", 403)
        mime, _ = mimetypes.guess_type(str(target))
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        # 파일명에 한글이 포함될 수 있어 HTTP 헤더는 latin-1 안전한 RFC 5987 형식 사용
        self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{quote(target.name)}")
        self.end_headers()
        self.wfile.write(body)


def _find_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return preferred


def make_server(port: int = 8420) -> ThreadingHTTPServer:
    """port=0 이면 OS가 빈 포트를 자동 할당(테스트용), 그 외에는 사용 가능한 포트를 탐색."""
    bind_port = port if port == 0 else _find_port(port)
    return ThreadingHTTPServer(("127.0.0.1", bind_port), Handler)


def run(port: int = 8420, open_browser: bool = True) -> None:
    server = make_server(port)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"14health 앱 실행 중: {url}")
    print("(로컬 전용 — 외부 접속 불가. 종료하려면 Ctrl+C)")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
