"""카톡 공유용 PNG 요약 카드 생성 (Pillow, 전부 로컬 처리).

Kakao API는 외부 전송·키 등록이 필요해 사용하지 않는다.
생성된 PNG를 사용자가 카카오톡에 직접 첨부해 공유한다.
이미지에는 실명 없이 관계호칭만 표기된다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, Optional

from health14 import analysis, vault

STATUS_COLORS = {"정상": "#1a9e5c", "주의": "#e8a13a", "위험": "#d94f45", "관찰": "#7a6dd7"}

FONT_CANDIDATES = [
    # Windows
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/malgunbd.ttf",
    # macOS
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/Library/Fonts/AppleGothic.ttf",
    # Linux
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]


def _fonts(size_body: int = 22):
    from PIL import ImageFont
    path = next((p for p in FONT_CANDIDATES if Path(p).exists()), None)
    if path is None:
        import warnings
        warnings.warn("한국어 폰트를 찾지 못했습니다 — 텍스트가 깨질 수 있습니다. "
                      "나눔고딕/Noto Sans KR 설치를 권장합니다.")
        default = ImageFont.load_default()
        return default, default, default
    body = ImageFont.truetype(path, size_body)
    bold = ImageFont.truetype(path, size_body)
    title = ImageFont.truetype(path, 32)
    return title, bold, body


def make_share_card(vault_path: Path, relation: str,
                    out: Optional[Path] = None,
                    report: Optional[Dict[str, Any]] = None) -> Path:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise SystemExit(
            "Pillow가 필요합니다: pip install Pillow\n"
            "또는 대시보드 HTML의 '공유 이미지 저장' 버튼을 사용하세요.")

    report = report or analysis.build_member_report(vault_path, relation)
    today = dt.date.today().isoformat()

    metrics = list(report["latest"].items())[:8]
    quarters = report["quarters"]
    q_items = sum(len(v) for v in quarters.values())

    summary = report.get("summary") or {}
    hl_line = None
    if summary.get("top_risk"):
        tr = summary["top_risk"]
        hl_line = f"⚠ {tr['metric']} {tr['status']} — {tr['action']}"
    elif summary.get("top_improvement"):
        hl_line = f"👍 {summary['top_improvement']['text']}"

    W = 720
    row_h = 52
    H = 220 + (44 if hl_line else 0) + len(metrics) * row_h + (260 if q_items else 60)
    img = Image.new("RGB", (W, H), "#f2f5fa")
    d = ImageDraw.Draw(img)
    f_title, f_bold, f_body = _fonts()

    # 헤더
    d.rounded_rectangle([0, -30, W, 100], radius=24, fill="#4a7bd0")
    d.text((26, 22), f"{relation} 건강 요약 ({report['age']}세 · {report['stage']})",
           font=f_title, fill="#ffffff")
    d.text((26, 64), f"14health · {today} · 로컬 생성", font=f_body, fill="#dbe6fa")

    y = 130
    if hl_line:
        color = "#d94f45" if summary.get("top_risk") else "#1a9e5c"
        d.rounded_rectangle([20, y - 8, W - 20, y + 28], radius=12, fill="#ffffff")
        d.text((38, y - 1), hl_line[:52], font=f_body, fill=color)
        y += 44
    d.text((26, y), "최근 검진 수치", font=f_title, fill="#1d2733")
    y += 50
    for name, info in metrics:
        d.rounded_rectangle([20, y, W - 20, y + row_h - 10], radius=12, fill="#ffffff")
        d.text((38, y + 10), str(name), font=f_body, fill="#67748a")
        value = info.get("value")
        value_s = f"{round(value, 1)} {info.get('unit', '')}".strip() if value is not None else "-"
        d.text((230, y + 10), value_s, font=f_bold, fill="#1d2733")
        status = info.get("status")
        if status:
            label = info.get("label", "")
            text = status + (f" ({label})" if label and label != status else "")
            d.text((400, y + 10), text, font=f_body,
                   fill=STATUS_COLORS.get(status, "#67748a"))
        y += row_h

    if q_items:
        y += 24
        d.text((26, y), "향후 1년 검진 계획", font=f_title, fill="#1d2733")
        y += 48
        for q in ("Q1", "Q2", "Q3", "Q4"):
            items = quarters.get(q) or []
            d.text((30, y), q, font=f_bold, fill="#4a7bd0")
            text = ", ".join(items) if items else "예정 없음"
            if len(text) > 42:
                text = text[:42] + "…"
            d.text((90, y), text, font=f_body, fill="#33405a")
            y += 40

    d.text((26, H - 34), "규칙 기반 참고 정보 · 의학적 진단 아님", font=f_body, fill="#8a94a6")

    if out is None:
        out_dir = vault_path / vault.EXPORT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{relation}-건강요약-{today}.png"
    img.save(out)
    return out
