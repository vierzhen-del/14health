"""14health CLI — 가족 건강기록 옵시디안 관리.

모든 건강 데이터는 로컬 옵시디안 vault에만 저장됩니다.
노션에는 마스킹된 이력(수치·실명 없음)만 선택적으로 동기화됩니다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from health14 import (analysis, anonymize, config, dashboard, export, family_io,
                      intake, md_io, notion_log, ocr, relations, share, vault,
                      webapp)


def _vault() -> Path:
    return config.get_vault_path()


def _parse_value(raw: str) -> Any:
    try:
        f = float(raw)
        return int(f) if f.is_integer() else f
    except ValueError:
        return raw


def _parse_fields(pairs: List[str]) -> Dict[str, Any]:
    """--field 혈압=120/80 --field 체중=72 ... → metrics dict."""
    metrics: Dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--field 형식 오류: {pair} (예: 체중=72, 혈압=120/80)")
        key, _, value = pair.partition("=")
        key, value = key.strip(), value.strip()
        if key == "혈압" and "/" in value:
            sys_v, _, dia_v = value.partition("/")
            metrics["수축기혈압"] = _parse_value(sys_v)
            metrics["이완기혈압"] = _parse_value(dia_v)
        else:
            metrics[key] = _parse_value(value)
    return metrics


# ---------------------------------------------------------------- 커맨드

def cmd_init(args) -> int:
    path = Path(args.vault).expanduser()
    vault.init_vault(path)
    config.set_vault_path(path)
    print(f"vault 생성 완료: {path}")
    print("다음 단계: 14health member add 나 --birth 1980 --sex M")
    return 0


def cmd_config(args) -> int:
    if args.action == "show":
        cfg = config.load_config()
        if "notion_token" in cfg:
            cfg["notion_token"] = "****"
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return 0
    if args.key == "vault":
        path = Path(args.value).expanduser()
        if not path.exists():
            raise SystemExit(f"경로가 존재하지 않습니다: {path}\n새로 만들려면 14health init --vault 사용")
        config.set_vault_path(path)
    else:
        cfg = config.load_config()
        cfg[args.key] = args.value
        config.save_config(cfg)
    print(f"설정 완료: {args.key}")
    return 0


def cmd_member(args) -> int:
    v = _vault()
    if args.action == "list":
        for m in vault.load_members(v):
            label = relations.display_name(m)
            cat = relations.member_category(m)
            extra = f" [{cat}]" if cat else ""
            print(f"- {label}{extra} — {m['relation']}, {m.get('birth_year')}년생, "
                  f"{m.get('sex')}, {vault.age_of(m)}세")
        return 0
    relation = args.relation
    info = relations.relation_info(relation)
    category = args.category or info["category"]
    if relation not in relations.all_relations():
        print(f"참고: '{relation}' 은 표준 관계호칭이 아닙니다 — '{info['name']}' 기준으로 "
              f"{category}/{relations.generation_label(info['generation'])}에 배치합니다. "
              "실명이 아닌 관계호칭인지 확인하세요.")
    vault.add_member(v, relation, args.birth, args.sex, category,
                     args.display or "")
    label = args.display or relation
    print(f"구성원 등록: {label} ({category}, {args.birth}년생, {args.sex})")
    if args.name:
        config.add_alias(args.name, relation)
        print(f"  실명 별칭 등록 완료 — 영수증에서 '{args.name}' 발견 시 자동으로 "
              f"'{label}' 기록으로 분류됩니다. (실명은 로컬 설정에만 저장)")
    return 0


def cmd_family(args) -> int:
    v = _vault()
    if args.action == "export":
        out = family_io.export_family(
            v, Path(args.out) if args.out else None, args.include_names)
        vault.log_action(v, "기타", "내보내기", "가족정보 JSON 내보내기")
        print(f"가족정보 내보내기 완료: {out}")
        if args.include_names:
            print("⚠️  이 파일에는 실명이 포함되어 있습니다 — 안전한 곳에 보관하세요.")
        return 0
    result = family_io.import_family_file(v, Path(args.path), args.restore_names)
    print(f"가족정보 가져오기 완료 — 추가 {len(result['added'])}명"
          f", 건너뜀 {len(result['skipped'])}명, 가족력 {result['history_added']}건")
    if result["added"]:
        print("  추가: " + ", ".join(result["added"]))
    if result["skipped"]:
        print("  이미 있어 건너뜀: " + ", ".join(result["skipped"]))
    if result["aliases_added"]:
        print(f"  실명 별칭 {result['aliases_added']}건 복원 (로컬 설정)")
    vault.log_action(v, "기타", "가져오기", "가족정보 JSON 가져오기")
    return 0


def cmd_relations(args) -> int:
    """등록 가능한 관계호칭을 카테고리별로 보여준다."""
    for cat in relations.categories():
        names = [r["name"] for r in cat["relations"]]
        print(f"[{cat['key']}] {', '.join(names)}")
    return 0


def cmd_alias(args) -> int:
    config.add_alias(args.name, args.relation)
    print(f"별칭 등록: 입력 텍스트의 '{args.name}' → '{args.relation}' 자동 치환 "
          "(매핑은 로컬 config에만 저장)")
    return 0


def cmd_checkup(args) -> int:
    v = _vault()
    metrics = _parse_fields(args.field or [])
    # 신장·체중이 있으면 BMI 자동 계산
    if "BMI" not in metrics and "신장" in metrics and "체중" in metrics:
        h = float(metrics["신장"]) / 100
        metrics["BMI"] = round(float(metrics["체중"]) / (h * h), 1)
    memo = anonymize.anonymize(args.memo or "")
    path = vault.add_checkup(v, args.relation, args.year, metrics, memo, args.date)
    vault.log_action(v, args.relation, "검진입력", f"{args.year} 건강검진 입력", path)
    print(f"검진 기록 저장: {path}")
    return 0


def cmd_visit(args) -> int:
    v = _vault()
    symptoms = [anonymize.anonymize(s) for s in (args.symptom or [])]
    medications = [anonymize.anonymize(m) for m in (args.rx or [])]
    cost = {k: intake._to_won(val)
            for k, val in _parse_fields(args.cost or []).items()}
    cost = {k: val for k, val in cost.items() if val is not None}
    path = vault.add_visit(
        v, args.relation, args.date, args.hospital, symptoms,
        anonymize.anonymize(args.diagnosis or ""), medications,
        anonymize.anonymize(args.memo or ""), cost)
    vault.log_action(v, args.relation, "진료입력", f"{args.hospital} 진료 기록", path)
    print(f"진료 기록 저장: {path}")
    return 0


def cmd_history(args) -> int:
    v = _vault()
    vault.add_family_history(v, args.relation, args.disease,
                             anonymize.anonymize(args.note or ""))
    vault.log_action(v, "기타", "가족력입력", f"가족력 추가 ({args.relation})",
                     v / vault.FAMILY_DIR / vault.HISTORY_FILE)
    print(f"가족력 추가: {args.relation} — {args.disease}")
    return 0


def cmd_note(args) -> int:
    """스킬(Claude/Gemini)이 분석 결과를 구조화 JSON으로 저장하는 진입점."""
    v = _vault()
    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    note_type = data.get("type")
    if note_type == "checkup":
        path = intake.apply_checkup(v, args.relation, data)
    elif note_type == "visit":
        path = intake.apply_visit(v, args.relation, data)
    else:
        raise SystemExit(f"지원하지 않는 type: {note_type} (checkup | visit)")
    print(f"노트 저장: {path}")
    return 0


def cmd_analyze(args) -> int:
    v = _vault()
    report = analysis.build_member_report(v, args.relation)
    path = analysis.write_analysis_note(v, args.relation, report)
    vault.log_action(v, args.relation, "위험분석", "위험도 분석 리포트 생성", path)
    print(f"분석 노트 저장: {path}")
    print()
    print(f"[{args.relation} · {report['age']}세 · {report['stage']}]")
    print(report["opinion"])
    if report["departments"]:
        print("\n권장 진료:")
        for d in report["departments"]:
            print(f"  - {d['dept']}: {d['cadence']}")
    return 0


def cmd_dashboard(args) -> int:
    v = _vault()
    out = dashboard.generate(v, Path(args.out) if args.out else None)
    vault.log_action(v, "기타", "대시보드생성", "가족 건강 대시보드 갱신", out)
    print(f"대시보드 생성: {out}")
    print("브라우저에서 열어 확인하세요 (외부 전송 없음).")
    return 0


def cmd_share(args) -> int:
    v = _vault()
    out = share.make_share_card(v, args.relation,
                                Path(args.out) if args.out else None)
    vault.log_action(v, args.relation, "공유이미지", "건강 요약 공유 이미지 생성")
    print(f"공유 이미지 생성: {out}")
    print("카카오톡에 직접 첨부해 공유하세요 (자동 전송 없음).")
    return 0


def cmd_export(args) -> int:
    v = _vault()
    out = export.export_vault(v, Path(args.out) if args.out else None)
    vault.log_action(v, "기타", "내보내기", "vault 전체 내보내기(zip)")
    print(f"내보내기 완료: {out}")
    print("새 기기에서: 14health import <zip> --vault <새 경로>")
    return 0


def cmd_import(args) -> int:
    new_vault = export.import_vault(Path(args.zip), Path(args.vault), args.overwrite)
    vault.log_action(new_vault, "기타", "가져오기", "vault 가져오기 완료")
    print(f"가져오기 완료: {new_vault}")
    print("vault 경로가 새 위치로 설정되었습니다.")
    return 0


def cmd_ocr(args) -> int:
    for r in ocr.extract_text(Path(args.target)):
        print(f"===== {r['file']} =====")
        print(anonymize.anonymize(r["text"]))
        print()
    print("※ 추출 텍스트를 확인 후 14health checkup add / visit add 로 저장하세요.")
    return 0


def cmd_md(args) -> int:
    v = _vault()
    if args.action == "export":
        files = md_io.export_member_md(v, args.relation)
        vault.log_action(v, args.relation, "내보내기", "구성원 기록 MD 내보내기")
        print(f"MD 내보내기 완료 ({len(files)}개):")
        for f in files:
            print(f"  - {f}")
        return 0
    # import
    results = md_io.import_md_path(v, Path(args.path), args.relation)
    saved = sum(1 for r in results if r["saved"])
    for r in results:
        name = Path(r["file"]).name
        if r["saved"]:
            print(f"저장됨: {name} → {r['path']}")
        elif r["kind"] == "parsed" and r["data"].get("metrics"):
            preview = ", ".join(f"{k}={v}" for k, v in r["data"]["metrics"].items())
            rel = r["data"].get("relation") or "(미지정 — --relation 필요)"
            year = r["data"].get("year") or "(연도 미확인)"
            print(f"확인 필요: {name} — 대상 {rel}, 연도 {year}, 추출 수치: {preview}")
            print("  → 확인 후 저장: 14health checkup add <관계호칭> --year <연도> "
                  + " ".join(f"--field {k}={v}" for k, v in r["data"]["metrics"].items()))
        else:
            print(f"건너뜀: {name} — {r.get('error', '추출할 데이터 없음')}")
    print(f"\n총 {len(results)}개 중 {saved}개 저장")
    return 0


def cmd_app(args) -> int:
    webapp.run(port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_log(args) -> int:
    v = _vault()
    if args.sync_notion:
        count = notion_log.sync(v)
        print(f"노션 동기화 완료: {count}건 (마스킹된 이력만 전송)")
        return 0
    for e in vault.load_log(v):
        print(f"{e['date']}  [{e['action']}] {e['target']} — {e['title']}")
    return 0


# ---------------------------------------------------------------- 파서

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="14health",
        description="가족 건강기록 옵시디안 관리 (로컬 전용, 관계호칭 익명화)")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="vault 생성·경로 설정")
    sp.add_argument("--vault", required=True, help="옵시디안 vault 경로")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("config", help="설정 관리")
    csub = sp.add_subparsers(dest="action", required=True)
    c1 = csub.add_parser("set", help="설정 값 지정")
    c1.add_argument("key", help="vault | notion_token | notion_database_id")
    c1.add_argument("value")
    csub.add_parser("show", help="설정 확인")
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser("member", help="구성원 관리 (관계호칭)")
    msub = sp.add_subparsers(dest="action", required=True)
    m1 = msub.add_parser("add", help="구성원 등록")
    m1.add_argument("relation", help="관계호칭 (나/부인/아들/딸/어머니 …). "
                                     "같은 관계가 여럿이면 '아들(첫째)' 처럼 구분")
    m1.add_argument("--birth", type=int, required=True, help="출생연도")
    m1.add_argument("--sex", choices=["M", "F"], required=True)
    m1.add_argument("--category", help="관계 분류 (미지정 시 관계호칭에서 자동 추론)")
    m1.add_argument("--display", help="화면 표시명 (기본: 관계호칭)")
    m1.add_argument("--name", help="영수증 자동매칭용 실명 (로컬 설정에만 저장)")
    msub.add_parser("list", help="구성원 목록")
    sp.set_defaults(func=cmd_member)

    sp = sub.add_parser("family", help="가족정보 JSON 내보내기/가져오기")
    fsub = sp.add_subparsers(dest="action", required=True)
    f1 = fsub.add_parser("export", help="구성원·가족력을 JSON으로 내보내기")
    f1.add_argument("--out", help="출력 경로 (기본: 90-내보내기/가족정보-<날짜>.json)")
    f1.add_argument("--include-names", action="store_true",
                    help="실명 별칭도 포함 (개인정보 — 기본 제외)")
    f2 = fsub.add_parser("import", help="가족정보 JSON 가져오기")
    f2.add_argument("path", help="가족정보 JSON 파일")
    f2.add_argument("--restore-names", action="store_true",
                    help="JSON에 실명이 있으면 별칭으로 복원")
    sp.set_defaults(func=cmd_family)

    sp = sub.add_parser("relations", help="등록 가능한 관계호칭 목록")
    sp.set_defaults(func=cmd_relations)

    sp = sub.add_parser("alias", help="실명→관계호칭 자동치환 등록")
    asub = sp.add_subparsers(dest="action", required=True)
    a1 = asub.add_parser("add")
    a1.add_argument("name", help="입력 자료에 나타나는 실명")
    a1.add_argument("relation", help="치환할 관계호칭")
    sp.set_defaults(func=cmd_alias)

    sp = sub.add_parser("checkup", help="건강검진 수치 입력")
    ksub = sp.add_subparsers(dest="action", required=True)
    k1 = ksub.add_parser("add")
    k1.add_argument("relation")
    k1.add_argument("--year", type=int, required=True)
    k1.add_argument("--date", help="검진일 (YYYY-MM-DD)")
    k1.add_argument("--field", action="append", metavar="항목=수치",
                    help="예: --field 혈압=120/80 --field 체중=72 --field 공복혈당=95")
    k1.add_argument("--memo", default="")
    sp.set_defaults(func=cmd_checkup)

    sp = sub.add_parser("visit", help="진료 기록 입력")
    vsub = sp.add_subparsers(dest="action", required=True)
    v1 = vsub.add_parser("add")
    v1.add_argument("relation")
    v1.add_argument("--date", required=True, help="진료일 (YYYY-MM-DD)")
    v1.add_argument("--hospital", required=True, help="병원종류 (내과/이비인후과 …)")
    v1.add_argument("--symptom", action="append", help="증상 (여러 번 지정 가능)")
    v1.add_argument("--diagnosis", default="", help="진단명")
    v1.add_argument("--rx", action="append", help="처방약 (여러 번 지정 가능)")
    v1.add_argument("--cost", action="append", metavar="항목=금액",
                    help="의료비 (예: --cost 본인부담금=34500 --cost 총액=95000)")
    v1.add_argument("--memo", default="")
    sp.set_defaults(func=cmd_visit)

    sp = sub.add_parser("history", help="가족력 입력")
    hsub = sp.add_subparsers(dest="action", required=True)
    h1 = hsub.add_parser("add")
    h1.add_argument("--relation", required=True, help="관계 (부/모/조부 …)")
    h1.add_argument("--disease", required=True, help="질환명")
    h1.add_argument("--note", default="")
    sp.set_defaults(func=cmd_history)

    sp = sub.add_parser("note", help="구조화 JSON 노트 저장 (스킬용)")
    nsub = sp.add_subparsers(dest="action", required=True)
    n1 = nsub.add_parser("write")
    n1.add_argument("relation")
    n1.add_argument("--json", required=True, help="checkup/visit JSON 파일 경로")
    sp.set_defaults(func=cmd_note)

    sp = sub.add_parser("analyze", help="위험도 분석 + 추천 리포트 생성")
    sp.add_argument("relation")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("dashboard", help="시각화 대시보드 HTML 생성")
    sp.add_argument("--out", help="출력 경로 (기본: <vault>/대시보드.html)")
    sp.set_defaults(func=cmd_dashboard)

    sp = sub.add_parser("share", help="카톡 첨부용 요약 PNG 생성")
    sp.add_argument("relation")
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_share)

    sp = sub.add_parser("export", help="vault 전체 내보내기(zip) — 기기 이동용")
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("import", help="vault zip 가져오기 + 경로 전환")
    sp.add_argument("zip")
    sp.add_argument("--vault", required=True, help="새 vault 경로")
    sp.add_argument("--overwrite", action="store_true")
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser("ocr", help="이미지 텍스트 추출 (tesseract 필요, 로컬 처리)")
    sp.add_argument("target", help="이미지 파일 또는 폴더")
    sp.set_defaults(func=cmd_ocr)

    sp = sub.add_parser("md", help="입력 결과 MD 내보내기/읽어오기")
    dsub = sp.add_subparsers(dest="action", required=True)
    d1 = dsub.add_parser("export", help="구성원의 검진·진료 노트를 MD로 내보내기")
    d1.add_argument("relation")
    d2 = dsub.add_parser("import", help="MD 파일/폴더를 vault로 읽어오기")
    d2.add_argument("path", help="md 파일 또는 폴더 경로")
    d2.add_argument("--relation", help="관계호칭 (md에 명시가 없을 때)")
    sp.set_defaults(func=cmd_md)

    sp = sub.add_parser("app", help="로컬 웹앱 실행 (브라우저 GUI, 외부 접속 불가)")
    sp.add_argument("--port", type=int, default=8420)
    sp.add_argument("--no-browser", action="store_true", help="브라우저 자동 오픈 안 함")
    sp.set_defaults(func=cmd_app)

    sp = sub.add_parser("log", help="작업 이력 조회 / 노션 동기화")
    sp.add_argument("--sync-notion", action="store_true",
                    help="마스킹된 이력만 노션에 동기화")
    sp.set_defaults(func=cmd_log)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
