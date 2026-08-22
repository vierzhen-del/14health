"""시각화 대시보드 생성 — 단일 자립형 HTML.

vault의 모든 데이터를 분석해 JSON으로 직렬화하고 templates/dashboard.html에
주입한다. 결과 파일은 외부 네트워크 요청이 전혀 없는 로컬 전용 페이지다.
"""
from __future__ import annotations

import datetime as dt
import json
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Optional

from health14 import analysis, recommend, relations, vault


def _member_payload(report: Dict[str, Any]) -> Dict[str, Any]:
    """build_member_report() 결과에서 대시보드에 필요한 부분만 추림."""
    keys = ["relation", "age", "sex", "birth_year", "stage", "series", "latest",
            "trends", "insights", "highlights", "tag_status", "profile",
            "treatment", "risks",
            "recommendations", "compliance", "cvd", "lifestyle", "departments",
            "quarters", "opinion", "summary"]
    return {k: report[k] for k in keys}


def build_data(vault_path: Path) -> Dict[str, Any]:
    members: List[Dict[str, Any]] = []
    for m in vault.load_members(vault_path):
        report = analysis.build_member_report(vault_path, m["relation"])
        payload = _member_payload(report)
        # 표시명·분류 — 없으면 관계호칭에서 추론 (기존 vault 하위호환)
        payload["display"] = relations.display_name(m)
        payload["category"] = relations.member_category(m)
        members.append(payload)
    ranges = {name: {"bands": d["bands"]}
              for name, d in recommend.reference_ranges()["metrics"].items()}
    return {
        "generated": dt.date.today().isoformat(),
        "members": members,
        "family": analysis.family_matrix(members),
        "lifecycle": recommend.lifecycle_stages(),
        "ranges": ranges,
    }


def generate(vault_path: Path, out: Optional[Path] = None) -> Path:
    template = (resources.files("health14")
                .joinpath("templates/dashboard.html").read_text(encoding="utf-8"))
    data = build_data(vault_path)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = template.replace("__DATA_JSON__", payload)
    out = out or (vault_path / "대시보드.html")
    out.write_text(html, encoding="utf-8")
    return out
