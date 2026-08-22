"""14health 로컬 웹앱 — 표준 라이브러리만 사용하는 localhost 전용 서버.

브라우저에서 대시보드를 보고 데이터를 입력할 수 있는 GUI 셸이다.
127.0.0.1에만 바인딩되며 외부에서 접근할 수 없다. 최초 실행 시 vault가
없으면 생성 화면을 보여주고, 한 번 생성되면 config에 경로가 저장되어
이후에는 해당 화면이 다시 나타나지 않는다.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import secrets
import socket
import subprocess
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, quote, urlparse

from health14 import (analysis, anonymize, calendar_index, config, dashboard,
                      export, family_io, insurance, intake, md_io, ocr, official,
                      parse, relations, share, treatment, vault)


# --lan 으로 실행할 때만 설정된다. None이면 토큰 검사를 하지 않는다(로컬 전용 모드).
ACCESS_TOKEN: Optional[str] = None


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
    payload["claims"] = insurance.claim_summary(v)
    payload["appointments"] = treatment.upcoming_summary(v)
    payload["upcoming"] = treatment.upcoming_visits(v)
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
        if ACCESS_TOKEN is not None:
            # 첫 접속 후에는 쿠키로 유지 — 이후 요청 URL에 토큰이 노출되지 않는다
            self.send_header("Set-Cookie",
                             f"h14token={ACCESS_TOKEN}; Path=/; SameSite=Strict")
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

    def _authorized(self, parsed) -> bool:
        """--lan 모드에서 1회용 토큰을 확인한다.

        토큰은 최초 접속 시 쿼리(?t=…)로 받고, 이후 요청은 쿠키로 유지한다.
        """
        if ACCESS_TOKEN is None:
            return True
        token = parse_qs(parsed.query).get("t", [None])[0]
        if token is None:
            cookie = self.headers.get("Cookie") or ""
            for part in cookie.split(";"):
                name, _, value = part.strip().partition("=")
                if name == "h14token":
                    token = value
                    break
        return secrets.compare_digest(token or "", ACCESS_TOKEN)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if not self._authorized(parsed):
            return self._error("접근 토큰이 필요합니다. 서버 실행 시 출력된 주소로 접속하세요.", 401)
        try:
            if path in ("/", "/index.html"):
                self._send_html(_app_html())
            elif path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            elif path == "/api/state":
                self._send_json(_state_payload())
            elif path == "/api/data":
                v = self._require_vault()
                if v:
                    self._send_json(_data_payload(v))
            elif path == "/api/calendar":
                v = self._require_vault()
                if v:
                    query = parse_qs(parsed.query)
                    year = query.get("year", [None])[0]
                    entries = calendar_index.build_index(
                        v, int(year) if year and year.isdigit() else None)
                    self._send_json({
                        "entries": entries,
                        "years": calendar_index.available_years(
                            calendar_index.build_index(v)),
                    })
            elif path == "/api/tree":
                v = self._require_vault()
                if v:
                    self._send_json(relations.build_family_tree(v))
            elif path == "/api/relations":
                self._send_json({"categories": relations.categories()})
            elif path == "/api/claims":
                v = self._require_vault()
                if v:
                    self._send_json({
                        "pending": insurance.pending_claims(v),
                        "summary": insurance.claim_summary(v),
                    })
            elif path == "/api/insurance":
                v = self._require_vault()
                if v:
                    query = parse_qs(parsed.query)
                    relation = query.get("relation", [None])[0]
                    if relation:
                        items = {relation: insurance.load_insurances(v, relation)}
                    else:
                        items = insurance.load_all_insurances(v)
                    self._send_json({"insurances": {
                        rel: [{k: val for k, val in i.items() if k != "_path"}
                              for i in lst]
                        for rel, lst in items.items()}})
            elif path == "/api/file":
                self._serve_file(parse_qs(parsed.query))
            else:
                self._error("Not Found", 404)
        except Exception as e:
            self._error(str(e), 500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if not self._authorized(parsed):
            return self._error("접근 토큰이 필요합니다.", 401)
        try:
            data = self._read_json()
            if path in ("/api/vault/create", "/api/vault/connect"):
                self._handle_vault_setup(data)
            elif path == "/api/member":
                self._handle_member(data)
            elif path == "/api/profile":
                self._handle_profile(data)
            elif path == "/api/treatment":
                self._handle_treatment(data)
            elif path == "/api/history":
                self._handle_history(data)
            elif path == "/api/note":
                self._handle_note(data)
            elif path == "/api/analyze":
                self._handle_analyze(data)
            elif path == "/api/recommend":
                self._handle_recommend(data)
            elif path == "/api/family/export":
                self._handle_family_export(data)
            elif path == "/api/family/import":
                self._handle_family_import(data)
            elif path == "/api/insurance":
                self._handle_insurance(data)
            elif path == "/api/dashboard/export":
                self._handle_dashboard_export()
            elif path == "/api/share":
                self._handle_share(data)
            elif path == "/api/export":
                self._handle_export()
            elif path == "/api/import":
                self._handle_import(data)
            elif path == "/api/parse-text":
                self._handle_parse_text(data)
            elif path == "/api/ocr":
                self._handle_ocr(data)
            elif path == "/api/official/parse":
                self._handle_official_parse(data)
            elif path == "/api/md/parse":
                self._handle_md_parse(data)
            elif path == "/api/md/import":
                self._handle_md_import(data)
            elif path == "/api/md/export":
                self._handle_md_export(data)
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
        category = (data.get("category") or "").strip()
        display = (data.get("display") or "").strip()
        vault.add_member(v, relation, int(data["birth"]), data["sex"],
                         category, display)
        # 실명은 vault가 아니라 로컬 설정에만 저장 (영수증 자동매칭용)
        real_name = (data.get("name") or "").strip()
        if real_name:
            config.add_alias(real_name, relation)
        self._send_json({"ok": True, "aliasAdded": bool(real_name)})

    def _handle_profile(self, data: Dict[str, Any]) -> None:
        v = self._require_vault()
        if not v:
            return
        relation = (data.get("relation") or "").strip()
        if not relation:
            return self._error("관계호칭을 입력하세요.")
        fields = {}
        if "smoking" in data and data["smoking"] is not None:
            fields["smoking"] = bool(data["smoking"])
        if "bp_treated" in data and data["bp_treated"] is not None:
            fields["bp_treated"] = bool(data["bp_treated"])
        vault.update_profile(v, relation, fields)
        vault.log_action(v, relation, "프로필수정", "건강 프로필 갱신")
        self._send_json({"ok": True})

    def _handle_treatment(self, data: Dict[str, Any]) -> None:
        """현재 진료내역 등록·종료 — 로직은 treatment 모듈이 갖는다."""
        v = self._require_vault()
        if not v:
            return
        relation = (data.get("relation") or "").strip()
        if not relation:
            return self._error("관계호칭을 입력하세요.")
        kind = (data.get("kind") or "").strip()
        if kind not in ("condition", "medication", "next_visit"):
            return self._error("kind는 condition/medication/next_visit 이어야 합니다.")
        if data.get("end"):
            treatment.end_item(v, relation, kind, (data.get("name") or "").strip())
            label = "치료 항목 종료"
        else:
            treatment.add_item(v, relation, kind, data.get("item") or {})
            label = "현재 진료내역 등록"
        vault.log_action(v, relation, "치료입력", label)
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

    def _handle_recommend(self, data: Dict[str, Any]) -> None:
        """예방 건강검진 추천 — 규칙 엔진만 사용(오프라인, 외부 전송 없음).

        relation을 주면 그 구성원, 없으면 가족 전원.
        """
        v = self._require_vault()
        if not v:
            return
        targets = ([data["relation"]] if data.get("relation")
                   else [m["relation"] for m in vault.load_members(v)])
        results = []
        for relation in targets:
            report = analysis.build_member_report(v, relation)
            member = vault.get_member(v, relation) or {}
            results.append({
                "relation": relation,
                "display": relations.display_name(member) if member else relation,
                "age": report["age"],
                "stage": report["stage"],
                "opinion": report["opinion"],
                "risks": report["risks"],
                "recommendations": report["recommendations"],
                "departments": report["departments"],
                "lifestyle": report["lifestyle"],
                "quarters": report["quarters"],
            })
            if data.get("save"):
                path = analysis.write_analysis_note(v, relation, report)
                vault.log_action(v, relation, "위험분석",
                                 "예방 검진 추천 리포트 생성", path)
        self._send_json({"results": results, "engine": "규칙 기반(오프라인)"})

    def _handle_family_export(self, data: Dict[str, Any]) -> None:
        v = self._require_vault()
        if not v:
            return
        out = family_io.export_family(v, None, bool(data.get("includeNames")))
        vault.log_action(v, "기타", "내보내기", "가족정보 JSON 내보내기")
        self._send_json({
            "ok": True, "path": str(out), "name": out.name,
            "url": f"/api/file?path={quote(out.relative_to(v).as_posix())}",
            "includesNames": bool(data.get("includeNames")),
        })

    def _handle_family_import(self, data: Dict[str, Any]) -> None:
        v = self._require_vault()
        if not v:
            return
        restore = bool(data.get("restoreNames"))
        if data.get("content") is not None:
            payload = json.loads(data["content"])
            result = family_io.import_family(v, payload, restore)
        elif data.get("path"):
            result = family_io.import_family_file(
                v, Path(data["path"]).expanduser(), restore)
        else:
            return self._error("content 또는 path가 필요합니다.")
        vault.log_action(v, "기타", "가져오기", "가족정보 JSON 가져오기")
        self._send_json({"ok": True, **result})

    def _handle_insurance(self, data: Dict[str, Any]) -> None:
        """보험 등록. 증권번호 같은 식별정보 필드는 스키마에 없어 저장되지 않는다."""
        v = self._require_vault()
        if not v:
            return
        relation = (data.get("relation") or "").strip()
        if not relation:
            return self._error("구성원을 선택하세요.")
        path = insurance.add_insurance(v, relation, data)
        vault.log_action(v, relation, "보험입력",
                         f"{data.get('보험사', '')} {data.get('상품명', '')} 등록".strip(),
                         path)
        self._send_json({"ok": True, "path": str(path)})

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

    def _handle_parse_text(self, data: Dict[str, Any]) -> None:
        """자유 텍스트 → 문서 종류 판별 + 후보 미리보기 (저장은 /api/note로 확정).

        kind가 "checkup"이면 검진 폼, "visit"이면 진료 폼을 채운다.
        """
        raw = data.get("text", "")
        vault_path = config.get_vault_path(required=False)
        known = ([m["relation"] for m in vault.load_members(vault_path)]
                 if vault_path and vault_path.exists() else None)
        match = parse.match_member(raw, config.get_aliases(), known)
        doc = parse.parse_document(anonymize.anonymize(raw))
        result = doc["data"]
        if match["relation"] and not result.get("relation"):
            result["relation"] = match["relation"]
        self._send_json({"kind": doc["kind"], "docType": doc["doc_type"],
                         "parsed": result, "matchedMember": match["relation"],
                         "matchedBy": match["matched_by"]})

    def _handle_ocr(self, data: Dict[str, Any]) -> None:
        """폴더 경로 또는 base64 이미지 → OCR 텍스트 + 문서 종류별 추출 결과.

        검진결과지·진료명세서·약국영수증을 자동 판별해 알맞은 폼으로 보낸다.
        원본 이미지는 저장하지 않고, 익명화된 텍스트만 반환한다.
        """
        if not ocr.tesseract_available():
            return self._error(
                "이 컴퓨터에 tesseract(로컬 OCR)가 설치되어 있지 않습니다. "
                "설치(macOS: brew install tesseract tesseract-lang / "
                "Windows: UB-Mannheim 배포판 / Ubuntu: apt install tesseract-ocr tesseract-ocr-kor) "
                "하거나, Claude Code의 /검진분석 스킬로 이미지를 분석하세요.", 422)
        if data.get("imageBase64"):
            suffix = Path(data.get("filename") or "image.png").suffix or ".png"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(base64.b64decode(data["imageBase64"]))
                tmp_path = Path(tmp.name)
            try:
                results = ocr.extract_text(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)
            if data.get("filename"):
                results[0]["file"] = data["filename"]
        elif data.get("folder"):
            folder = Path(data["folder"]).expanduser()
            if not folder.exists():
                return self._error(f"폴더가 없습니다: {folder}")
            results = ocr.extract_text(folder)
        else:
            return self._error("folder 또는 imageBase64가 필요합니다.")
        # 등록된 실명·구성원 목록 (자동매칭용). vault가 없으면 매칭은 건너뛴다.
        aliases = config.get_aliases()
        vault_path = config.get_vault_path(required=False)
        known = ([m["relation"] for m in vault.load_members(vault_path)]
                 if vault_path and vault_path.exists() else None)

        out = []
        for r in results:
            raw = r["text"]
            # ① 매칭은 반드시 익명화 이전 원문으로 (익명화하면 실명이 사라짐)
            match = parse.match_member(raw, aliases, known)
            # ② 익명화 후에는 원문을 더 쓰지 않는다
            text = anonymize.anonymize(raw)
            doc = parse.parse_document(text)
            data = doc["data"]
            if match["relation"] and not data.get("relation"):
                data["relation"] = match["relation"]
            out.append({"file": r["file"], "text": text, "kind": doc["kind"],
                        "docType": doc["doc_type"], "parsed": data,
                        "matchedMember": match["relation"],
                        "matchedBy": match["matched_by"]})
        self._send_json({"results": out})

    def _handle_official_parse(self, data: Dict[str, Any]) -> None:
        """공단·심평원 공식 파일 파싱 미리보기 (저장은 /api/note 로 확정).

        경로만 받고 파일은 로컬에서 읽는다. 인증정보는 앱을 거치지 않는다.
        """
        v = self._require_vault()
        if not v:
            return
        raw_path = (data.get("path") or "").strip()
        if not raw_path:
            return self._error("파일 경로를 입력하세요.")
        target = Path(raw_path).expanduser()
        if not target.exists():
            return self._error(f"파일이 없습니다: {target}")

        aliases = config.get_aliases()
        known = [m["relation"] for m in vault.load_members(v)]
        out = []
        for r in official.parse_path(target):
            raw = r.pop("text", "")
            match = parse.match_member(raw, aliases, known)
            item = dict(r)
            item["parsed"] = r["data"]
            if match["relation"] and not item["parsed"].get("relation"):
                item["parsed"]["relation"] = match["relation"]
            item["matchedMember"] = match["relation"]
            item["matchedBy"] = match["matched_by"]
            item["text"] = anonymize.anonymize(raw)[:1500]
            item["docType"] = r["doc_type"]
            item.pop("data", None)
            item.pop("doc_type", None)
            out.append(item)
        self._send_json({"results": out})

    def _handle_md_parse(self, data: Dict[str, Any]) -> None:
        """md 내용 미리보기 — 저장하지 않고 해석 결과만 반환."""
        v = self._require_vault()
        if not v:
            return
        result = md_io.import_md_content(v, data.get("content", ""),
                                         data.get("relation"), confirm_only=True)
        self._send_json(result)

    def _handle_md_import(self, data: Dict[str, Any]) -> None:
        """md 확정 저장 — content(업로드) 또는 path(파일/폴더)."""
        v = self._require_vault()
        if not v:
            return
        relation = data.get("relation")
        if data.get("content") is not None:
            result = md_io.import_md_content(v, data["content"], relation)
            self._send_json(result)
        elif data.get("path"):
            results = md_io.import_md_path(v, Path(data["path"]).expanduser(), relation)
            self._send_json({"results": results})
        else:
            self._error("content 또는 path가 필요합니다.")

    def _handle_md_export(self, data: Dict[str, Any]) -> None:
        v = self._require_vault()
        if not v:
            return
        relation = data["relation"]
        files = md_io.export_member_md(v, relation)
        vault.log_action(v, relation, "내보내기", "구성원 기록 MD 내보내기")
        payload = [{"name": f.name,
                    "url": f"/api/file?path={quote(f.relative_to(v).as_posix())}"}
                   for f in files]
        self._send_json({"ok": True, "dir": str(files[0].parent) if files else "",
                         "files": payload})

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


def make_server(port: int = 8420, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """port=0 이면 OS가 빈 포트를 자동 할당(테스트용), 그 외에는 사용 가능한 포트를 탐색."""
    bind_port = port if port == 0 else _find_port(port)
    return ThreadingHTTPServer((host, bind_port), Handler)


def _lan_ip() -> str:
    """이 기기의 LAN/Tailscale IP 추정 (실제 연결은 만들지 않는다).

    안드로이드에서 Tailscale이 시스템 VPN(VpnService)으로 동작하면 라우팅
    테이블의 기본 경로가 tailnet IP가 아니라 VPN 터널 어댑터의 placeholder
    주소(흔히 192.0.0.2)를 가리켜, 소켓 트릭만으로는 잘못된 주소가 잡힌다.
    `tailscale` CLI가 있으면 그쪽을 먼저 신뢰한다.
    """
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError):
        pass

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def run(port: int = 8420, open_browser: bool = True, lan: bool = False) -> None:
    """앱 실행.

    기본은 127.0.0.1 전용. `lan=True` 면 0.0.0.0에 바인딩해 같은 네트워크
    (집 와이파이·Tailscale)의 폰·PC에서 접속할 수 있게 하되, **1회용 토큰**을
    발급해 URL을 아는 사람만 들어오도록 막는다. 토큰 없이 열리는 실수를 막기 위해
    토큰은 켜는 순간 무조건 생성된다.
    """
    global ACCESS_TOKEN
    host = "0.0.0.0" if lan else "127.0.0.1"
    if lan:
        ACCESS_TOKEN = secrets.token_urlsafe(16)

    server = make_server(port, host)
    actual_port = server.server_address[1]

    if lan:
        url = f"http://{_lan_ip()}:{actual_port}/?t={ACCESS_TOKEN}"
        print(f"14health 앱 실행 중 (LAN 공개): {url}")
        print("  ↑ 이 주소를 폰에서 열면 됩니다. 토큰이 없으면 접속이 거부됩니다.")
        print("  같은 네트워크(집 와이파이/Tailscale) 안에서만 접근 가능 —")
        print("  공용 와이파이에서는 --lan 을 쓰지 마세요.")
    else:
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
