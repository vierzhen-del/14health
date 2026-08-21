"""선택 구성원의 위험도 분석 + 추천 리포트 생성.

검진 노트 frontmatter의 수치들을 모아 연도별 추이·기준치 판정·가족력 가중
위험요인을 계산하고, 권장 검진/생활습관/진료과·주기를 담은 분석 노트를
vault에 생성한다. 대시보드도 동일한 build_member_report() 결과를 사용한다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

from health14 import recommend, vault

CORE_METRICS = [
    "수축기혈압", "이완기혈압", "공복혈당", "식후혈당", "당화혈색소",
    "BMI", "체중", "허리둘레", "총콜레스테롤", "LDL", "HDL", "중성지방",
    "AST", "ALT", "감마GTP", "크레아티닌", "eGFR", "혈색소",
]

# 시계열 전체의 예측 변화량이 평균 절대값의 이 비율 미만이면 "유지"로 본다.
# (알고리즘 상수 — 의학 기준 아님. 의학 기준은 data/guidelines/*.yaml 에만 둔다)
STABLE_RATIO = 0.02


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def series_insights(series: Dict[str, List[Dict[str, Any]]],
                    sex: str = "") -> Dict[str, Dict[str, Any]]:
    """시계열 전체를 본 추이 인사이트 (2개 이상 시점이 있는 항목만).

    trends(최근 2개 시점 비교)와 달리 전체 기울기·최고/최저·연속 스트릭·
    판정 변화를 계산한다. higher_is_better 항목(HDL·eGFR·혈색소)은 방향을
    뒤집어 해석한다.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for metric, points in series.items():
        if len(points) < 2:
            continue
        pts = sorted(points, key=lambda p: (p.get("year") or 0))
        xs = [float(p.get("year") or i) for i, p in enumerate(pts)]
        ys = [p["value"] for p in pts]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        denom = sum((x - mx) ** 2 for x in xs)
        slope = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
                 if denom else 0.0)
        total_change = slope * (xs[-1] - xs[0])
        mean_abs = sum(abs(y) for y in ys) / n or 1.0

        mdef = recommend.metric_def(metric, sex) or {}
        hib = bool(mdef.get("higher_is_better"))
        if abs(total_change) < STABLE_RATIO * mean_abs:
            direction = "유지"
        else:
            worse = total_change > 0
            direction = "악화" if (worse != hib) else "개선"

        best = (max if hib else min)(pts, key=lambda p: p["value"])
        worst = (min if hib else max)(pts, key=lambda p: p["value"])

        # 마지막 시점 기준 연속 개선/악화 스트릭 (스텝 수 = 시점 수 - 1)
        steps: List[str] = []
        for a, b in zip(pts, pts[1:]):
            d = b["value"] - a["value"]
            if abs(d) < 1e-9:
                steps.append("유지")
            else:
                steps.append("악화" if ((d > 0) != hib) else "개선")
        streak = {"kind": "", "count": 0}
        if steps and steps[-1] != "유지":
            kind = steps[-1]
            count = 0
            for s in reversed(steps):
                if s != kind:
                    break
                count += 1
            streak = {"kind": kind, "count": count}

        c_first = recommend.classify(metric, pts[0]["value"], sex)
        c_last = recommend.classify(metric, pts[-1]["value"], sex)
        status_change = None
        if c_first and c_last and c_first["status"] != c_last["status"]:
            status_change = f"{c_first['status']}→{c_last['status']}"

        out[metric] = {
            "direction": direction,
            "change_since_first": round(pts[-1]["value"] - pts[0]["value"], 2),
            "first_year": pts[0].get("year"),
            "last_year": pts[-1].get("year"),
            "best": {"year": best.get("year"), "value": best["value"]},
            "worst": {"year": worst.get("year"), "value": worst["value"]},
            "streak": streak,
            "status_change": status_change,
        }
    return out


def build_highlights(insights: Dict[str, Dict[str, Any]],
                     latest: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """자동 하이라이트 (Apple Health Trends 스타일).

    severity: 2=경고(악화·판정 악화), 0=긍정(개선·최고 기록). 심각한 것 먼저.
    """
    items: List[Dict[str, Any]] = []
    for metric, ins in insights.items():
        sc = ins.get("status_change")
        if sc:
            first, _, last = sc.partition("→")
            worsened = (recommend.STATUS_ORDER.get(last, 0)
                        > recommend.STATUS_ORDER.get(first, 0))
            items.append({
                "metric": metric,
                "kind": "entered_risk" if worsened else "returned_normal",
                "severity": 2 if worsened else 0,
                "text": (f"{metric} 판정이 {sc}로 "
                         + ("바뀌었습니다" if worsened else "좋아졌습니다")),
            })
        st = ins["streak"]
        at_best = (ins["best"].get("year") == ins.get("last_year"))
        if st["kind"] == "악화" and st["count"] >= 2:
            items.append({
                "metric": metric, "kind": "streak_worse", "severity": 2,
                "text": f"{metric} {st['count']}회 연속 악화 추세",
            })
        elif st["kind"] == "개선" and st["count"] >= 2:
            items.append({
                "metric": metric, "kind": "streak_better", "severity": 0,
                "text": (f"{metric} {st['count']}회 연속 개선"
                         + (" — 기록상 최고" if at_best else "")),
            })
        elif at_best and ins["direction"] == "개선":
            items.append({
                "metric": metric, "kind": "personal_best", "severity": 0,
                "text": f"{metric} 최근 수치가 기록상 가장 좋습니다",
            })
    items.sort(key=lambda h: -h["severity"])
    return items


def build_member_report(vault_path: Path, relation: str,
                        today: Optional[dt.date] = None) -> Dict[str, Any]:
    """분석에 필요한 모든 데이터를 구조화해 반환."""
    member = vault.get_member(vault_path, relation)
    if member is None:
        raise SystemExit(f"등록되지 않은 구성원입니다: {relation}")
    today = today or dt.date.today()
    age = vault.age_of(member, today)
    sex = member.get("sex", "")

    checkups = vault.load_checkups(vault_path, relation)
    visits = vault.load_visits(vault_path, relation)
    family_diseases = [h["disease"] for h in vault.load_family_history(vault_path)]

    # 연도별 시계열
    series: Dict[str, List[Dict[str, Any]]] = {}
    for c in checkups:
        year = c.get("year")
        for metric, raw in (c.get("metrics") or {}).items():
            v = _to_float(raw)
            if v is None:
                continue
            series.setdefault(metric, []).append({"year": year, "value": v})

    # 최근 수치 판정
    latest: Dict[str, Dict[str, Any]] = {}
    tag_status: Dict[str, str] = {}
    for metric, points in series.items():
        value = points[-1]["value"]
        cls = recommend.classify(metric, value, sex)
        entry: Dict[str, Any] = {"value": value, "year": points[-1]["year"]}
        if cls:
            entry.update(cls)
            tag = cls["tag"]
            if tag:
                prev = tag_status.get(tag, "정상")
                if recommend.STATUS_ORDER[cls["status"]] > recommend.STATUS_ORDER[prev]:
                    tag_status[tag] = cls["status"]
                else:
                    tag_status.setdefault(tag, prev)
        latest[metric] = entry

    # 추이 (최근 2개 시점 비교)
    trends: Dict[str, str] = {}
    for metric, points in series.items():
        if len(points) >= 2:
            diff = points[-1]["value"] - points[-2]["value"]
            mdef = recommend.metric_def(metric, sex) or {}
            worse = diff > 0
            if mdef.get("higher_is_better"):
                worse = diff < 0
            if abs(diff) < 1e-9:
                trends[metric] = "유지"
            else:
                trends[metric] = "악화" if worse else "개선"

    # 위험요인: 주의/위험 판정 + 가족력 가중
    fh_tags = recommend.family_history_tags(family_diseases)
    risks: List[Dict[str, Any]] = []
    for metric, info in latest.items():
        status = info.get("status")
        if status in ("주의", "위험"):
            fh_hit = info.get("tag") in fh_tags
            risks.append({
                "metric": metric,
                "value": info["value"],
                "unit": info.get("unit", ""),
                "status": status,
                "label": info.get("label", status),
                "trend": trends.get(metric, ""),
                "family_history": fh_hit,
            })
    # 가족력만 있고 수치는 정상/미측정인 태그도 관찰 대상으로 표시
    for tag in fh_tags:
        if tag_status.get(tag, "정상") == "정상":
            risks.append({
                "metric": f"{tag}(가족력)",
                "value": None, "unit": "",
                "status": "관찰",
                "label": "수치는 정상 범위 — 가족력으로 정기 관찰 필요",
                "trend": "", "family_history": True,
            })
    risks.sort(key=lambda r: -recommend.STATUS_ORDER.get(r["status"], 0))

    risk_tags: List[str] = []
    for r in risks:
        tag = (latest.get(r["metric"]) or {}).get("tag", "")
        if tag and tag not in risk_tags:
            risk_tags.append(tag)
    for tag in fh_tags:
        if tag not in risk_tags:
            risk_tags.append(tag)

    insights = series_insights(series, sex)
    highlights = build_highlights(insights, latest)

    recs = recommend.recommended_checkups(age, sex, family_diseases)
    advice = recommend.lifestyle_advice(age, risk_tags)
    departments = recommend.department_advice(tag_status)
    quarters = recommend.quarterly_plan(recs)
    stage = recommend.stage_of(age)

    opinion = _build_opinion(relation, age, risks, departments, trends)

    return {
        "relation": relation,
        "age": age,
        "sex": sex,
        "birth_year": member.get("birth_year"),
        "stage": stage["stage"],
        "series": series,
        "latest": latest,
        "trends": trends,
        "insights": insights,
        "highlights": highlights,
        "risks": risks,
        "risk_tags": risk_tags,
        "family_diseases": family_diseases,
        "recommendations": recs,
        "lifestyle": advice,
        "departments": departments,
        "quarters": quarters,
        "visits": visits,
        "opinion": opinion,
    }


def _build_opinion(relation: str, age: int, risks: List[Dict[str, Any]],
                   departments: List[Dict[str, str]], trends: Dict[str, str]) -> str:
    parts: List[str] = []
    danger = [r for r in risks if r["status"] == "위험"]
    caution = [r for r in risks if r["status"] == "주의"]
    if danger:
        parts.append("⚠️ " + ", ".join(r["metric"] for r in danger)
                     + " 항목이 위험 범위입니다. 빠른 진료 상담을 권합니다.")
    if caution:
        parts.append(", ".join(r["metric"] for r in caution)
                     + " 항목은 주의 범위로 생활습관 개선과 추적 관찰이 필요합니다.")
    fh = [r for r in risks if r.get("family_history")]
    if fh:
        parts.append("가족력 관련 항목(" + ", ".join(r["metric"] for r in fh)
                     + ")은 정기적인 모니터링이 필요합니다.")
    worsening = [m for m, t in trends.items() if t == "악화"]
    if worsening:
        parts.append("최근 " + ", ".join(worsening) + " 수치가 이전 검진 대비 악화 추세입니다.")
    if not parts:
        parts.append(f"현재 등록된 수치는 모두 정상 범위입니다. {age}세 권장 검진 주기를 유지하세요.")
    return " ".join(parts)


def write_analysis_note(vault_path: Path, relation: str,
                        report: Optional[Dict[str, Any]] = None) -> Path:
    """분석 결과를 옵시디안 노트로 저장."""
    report = report or build_member_report(vault_path, relation)
    today = dt.date.today()
    path = (vault_path / vault.MEMBERS_DIR / relation / "분석"
            / f"{today.strftime('%Y-%m')}-위험도분석.md")

    lines: List[str] = [f"# {relation} 위험도 분석 ({today.isoformat()})", ""]
    lines += [f"- 나이: {report['age']}세 ({report['stage']})", ""]

    if report.get("highlights"):
        lines.append("## 하이라이트")
        lines.append("")
        for h in report["highlights"]:
            mark = "⚠️" if h["severity"] >= 2 else "👍"
            lines.append(f"- {mark} {h['text']}")
        lines.append("")

    lines.append("## 주요 질병 위험도")
    lines.append("")
    if report["risks"]:
        lines.append("| 항목 | 수치 | 판정 | 추이 | 가족력 |")
        lines.append("|---|---|---|---|---|")
        for r in report["risks"]:
            value = f"{r['value']} {r['unit']}".strip() if r["value"] is not None else "-"
            lines.append(
                f"| {r['metric']} | {value} | {r['status']} ({r['label']}) "
                f"| {r['trend'] or '-'} | {'예' if r['family_history'] else '-'} |")
    else:
        lines.append("등록된 수치 기준 위험 요인이 없습니다.")
    lines.append("")

    if report["trends"]:
        lines.append("## 연도별 추이")
        lines.append("")
        lines.append("| 항목 | 추이 | 최근 수치 |")
        lines.append("|---|---|---|")
        for metric, t in report["trends"].items():
            info = report["latest"].get(metric, {})
            lines.append(f"| {metric} | {t} | {info.get('value', '-')} {info.get('unit', '')} |")
        lines.append("")

    lines.append("## 권장 검진 항목·주기")
    lines.append("")
    for rec in report["recommendations"]:
        fh = " **(가족력 강화)**" if rec["family_history"] else ""
        lines.append(f"- {rec['name']} — {rec['interval_years']}년 주기{fh}"
                     + (f" · {rec['detail']}" if rec.get("detail") else ""))
    lines.append("")

    lines.append("## 향후 1년 검진 계획")
    lines.append("")
    for q in ("Q1", "Q2", "Q3", "Q4"):
        items = report["quarters"].get(q) or []
        lines.append(f"- **{q}**: " + (", ".join(items) if items else "-"))
    lines.append("")

    if report["departments"]:
        lines.append("## 권장 진료·방문 주기")
        lines.append("")
        for d in report["departments"]:
            lines.append(f"- {d['dept']} — {d['cadence']} (관련: {d['tag']} {d['status']})")
        lines.append("")

    lines.append("## 생활습관 권고")
    lines.append("")
    for adv in report["lifestyle"]["risk"]:
        lines.append(f"- [위험관리] {adv}")
    for adv in report["lifestyle"]["age_band"]:
        lines.append(f"- {adv}")
    lines.append("")

    lines.append("## 종합 소견")
    lines.append("")
    lines.append(report["opinion"])
    lines.append("")
    lines.append("> 본 분석은 규칙 기반 참고 정보이며 의학적 진단이 아닙니다. "
                 "이상 소견은 반드시 의료진과 상담하세요.")

    meta = {
        "type": "analysis",
        "member": relation,
        "date": today.isoformat(),
        "risk_count": len(report["risks"]),
    }
    vault.write_note(path, meta, "\n".join(lines) + "\n")
    return path
