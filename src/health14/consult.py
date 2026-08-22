"""AI 상담 브리핑 — 상담에 쓸 내용을 로컬에서 구조화해 만든다.

**이 모듈은 아무 데도 전송하지 않는다.** 브리핑을 만들어 보여줄 뿐이고,
그걸 Claude 에 붙여넣을지는 사용자가 결정한다(카톡 공유 PNG 와 같은 원칙 —
자동 전송 기능은 없다). Claude Code·모바일 앱은 MCP 로 이 결과를 직접
읽으므로 복사·붙여넣기 없이도 상담할 수 있다.

브리핑에는 **수치가 들어간다** — 그게 상담의 목적이다. 대신 실명·주민번호·
식별번호는 들어가지 않는다(vault 저장 시점에 anonymize 가 이미 제거하고,
여기서 한 번 더 통과시킨다). 숫자를 모두 지우는 `mask_for_external()` 은
노션 전용 변환이라 여기 쓰지 않는다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

from health14 import analysis, anonymize, treatment, vault

DISCLAIMER = ("규칙 기반 참고 정보이며 의학적 진단이 아닙니다. "
              "실제 진단·처방은 반드시 의료진과 상담하세요.")

COPY_WARNING = ("이 브리핑에는 건강 수치가 들어 있습니다 — "
                "붙여넣는 곳이 어디인지 확인하세요. (실명·주민번호는 없습니다)")


def _member_briefing(vault_path: Path, relation: str,
                     today: dt.date) -> Dict[str, Any]:
    report = analysis.build_member_report(vault_path, relation, today)
    t = report.get("treatment") or {}

    metrics = []
    for name, info in (report.get("latest") or {}).items():
        metrics.append({
            "항목": name,
            "값": info.get("value"),
            "단위": info.get("unit", ""),
            "판정": info.get("status", ""),
            "연도": info.get("year"),
            "추이": (report.get("trends") or {}).get(name, ""),
        })

    cvd = report.get("cvd")
    cvd_out = None
    if cvd and not cvd.get("diabetes_equivalent"):
        cvd_out = {
            "혈관나이": cvd["heart_age"],
            "실제나이차": cvd["heart_age_gap"],
            "동일연령_최적대비": cvd["relative"],
            "위험구간": cvd["band"],
            "가정": cvd.get("assumptions") or [],
        }
    elif cvd:
        cvd_out = {"비고": cvd.get("note", "")}

    return {
        "대상": report["relation"],
        "나이": report["age"],
        "성별": "여" if report["sex"] == "F" else "남",
        "생애주기": report["stage"],
        "가족력": [{"관계": h["relation"], "질환": h["disease"]}
                 for h in report.get("family_history") or []],
        "현재_치료중": [
            {"질환": c["name"], "상태": c.get("status", ""),
             "진료과": c.get("dept", ""), "시작": c.get("since", "")}
            for c in treatment.active_conditions(t)],
        "복약중": [{"약": m["name"], "용법": m.get("dose", ""),
                 "대상질환": m.get("for", "")}
                for m in t.get("medications") or []],
        "다음_예약": [{"날짜": n["date"], "진료과": n.get("dept", ""),
                   "목적": n.get("purpose", "")}
                  for n in t.get("next_visits") or []],
        "최근_검진": metrics,
        "교차_소견": [{"내용": f["text"], "권고": f.get("action", ""),
                   "심각도": f["severity"]}
                  for f in report.get("findings") or []],
        "심혈관_위험": cvd_out,
        "검진_이행률": (report.get("compliance") or {}).get("rate"),
        "지연된_검진": [i["name"] for i in (report.get("compliance") or {}).get("overdue") or []],
    }


def build_briefing(vault_path: Path, relation: Optional[str] = None,
                   today: Optional[dt.date] = None) -> Dict[str, Any]:
    """상담용 브리핑. relation 을 생략하면 가족 전체."""
    today = today or dt.date.today()
    members = vault.load_members(vault_path)
    if relation:
        if not any(m["relation"] == relation for m in members):
            raise SystemExit(f"등록되지 않은 구성원입니다: {relation}")
        targets = [relation]
    else:
        targets = [m["relation"] for m in members]
    if not targets:
        raise SystemExit("등록된 구성원이 없습니다.")

    people = [_member_briefing(vault_path, r, today) for r in targets]
    briefing = {
        "생성일": today.isoformat(),
        "구성원": people,
        "면책": DISCLAIMER,
    }
    briefing["추천_질문"] = suggest_questions(briefing)
    return briefing


def suggest_questions(briefing: Dict[str, Any]) -> List[str]:
    """교차 소견에서 규칙으로 뽑은 '이런 걸 물어보세요'."""
    questions: List[str] = []
    for person in briefing.get("구성원") or []:
        who = person["대상"]
        for f in person.get("교차_소견") or []:
            text = f["내용"]
            if "치료 중인데" in text and "위험" in text:
                questions.append(
                    f"{who}: 약을 먹고 있는데 수치가 목표에 못 미칩니다 — "
                    "용량 조절이나 다른 치료를 검토해야 할까요?")
            elif "치료 기록이 없습니다" in text:
                questions.append(
                    f"{who}: 이 수치가 지금 치료를 시작해야 할 수준인가요, "
                    "생활습관 교정으로 지켜봐도 될까요?")
            elif "재지 않았습니다" in text or "기록이 없습니다" in text:
                questions.append(
                    f"{who}: 복용 중인 약과 관련해 어떤 검사를 얼마나 자주 "
                    "받아야 하나요?")
        if person.get("가족력") and person.get("현재_치료중"):
            questions.append(
                f"{who}: 가족력을 고려하면 지금 받는 관리로 충분한가요?")
        cvd = person.get("심혈관_위험") or {}
        if cvd.get("혈관나이") and (cvd.get("실제나이차") or 0) > 0:
            questions.append(
                f"{who}: 혈관나이가 실제 나이보다 높게 나왔는데 "
                "가장 먼저 바꿔야 할 것은 무엇인가요?")
        if person.get("지연된_검진"):
            questions.append(
                f"{who}: 미뤄진 검진 중 우선순위가 높은 것은 무엇인가요?")
    # 중복 제거(순서 유지)
    seen = set()
    out = []
    for q in questions:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def render_text(briefing: Dict[str, Any]) -> str:
    """복사해서 붙여넣기 좋은 마크다운. 실명·식별번호는 한 번 더 걸러낸다."""
    lines: List[str] = [
        f"# 가족 건강 상담 브리핑 ({briefing['생성일']})", "",
        "> 관계호칭만 사용하며 실명·주민번호·식별번호는 포함되지 않습니다.", "",
    ]
    for p in briefing.get("구성원") or []:
        lines.append(f"## {p['대상']} ({p['나이']}세 · {p['성별']} · {p['생애주기']})")
        lines.append("")

        if p["가족력"]:
            fh = ", ".join(f"{h['관계']}: {h['질환']}" for h in p["가족력"])
            lines.append(f"- **가족력**: {fh}")
        if p["현재_치료중"]:
            cur = ", ".join(
                c["질환"] + (f"({c['상태']})" if c["상태"] else "")
                for c in p["현재_치료중"])
            lines.append(f"- **현재 치료중**: {cur}")
        if p["복약중"]:
            meds = ", ".join(
                m["약"] + (f" {m['용법']}" if m["용법"] else "")
                for m in p["복약중"])
            lines.append(f"- **복약중**: {meds}")
        if p["다음_예약"]:
            appt = ", ".join(
                f"{n['날짜']}" + (f" {n['진료과']}" if n["진료과"] else "")
                for n in p["다음_예약"])
            lines.append(f"- **다음 예약**: {appt}")
        if p["검진_이행률"] is not None:
            overdue = (f" (지연: {', '.join(p['지연된_검진'])})"
                       if p["지연된_검진"] else "")
            lines.append(f"- **검진 이행률**: {p['검진_이행률']}%{overdue}")
        lines.append("")

        if p["최근_검진"]:
            lines.append("### 최근 검진 수치")
            lines.append("")
            lines.append("| 항목 | 값 | 판정 | 추이 | 연도 |")
            lines.append("|---|---|---|---|---|")
            for m in p["최근_검진"]:
                unit = f" {m['단위']}" if m["단위"] else ""
                lines.append(
                    f"| {m['항목']} | {m['값']}{unit} | {m['판정'] or '-'} "
                    f"| {m['추이'] or '-'} | {m['연도'] or '-'} |")
            lines.append("")

        cvd = p.get("심혈관_위험")
        if cvd and cvd.get("혈관나이"):
            gap = cvd["실제나이차"]
            lines.append(
                f"### 심혈관 위험 (참고)\n\n"
                f"- 혈관나이 {cvd['혈관나이']}세"
                + (f" (실제보다 +{gap}세)" if gap > 0 else "")
                + f" · 같은 나이·성별 최적 상태 대비 약 {cvd['동일연령_최적대비']}배"
                + f" · 위험구간 {cvd['위험구간']}")
            for a in cvd.get("가정") or []:
                lines.append(f"- 가정: {a}")
            lines.append("")

        if p["교차_소견"]:
            lines.append("### 종합 소견 (가족력 · 현재 치료 · 검진수치 교차)")
            lines.append("")
            for f in p["교차_소견"]:
                mark = {2: "⚠️", 1: "🔎"}.get(f["심각도"], "👍")
                lines.append(f"- {mark} {f['내용']}"
                             + (f" → {f['권고']}" if f["권고"] else ""))
            lines.append("")

    if briefing.get("추천_질문"):
        lines.append("## 이런 걸 물어보세요")
        lines.append("")
        for q in briefing["추천_질문"]:
            lines.append(f"- {q}")
        lines.append("")

    lines.append(f"> {briefing['면책']}")
    return anonymize.anonymize("\n".join(lines) + "\n")
