"""옵시디안 vault 구조 생성과 노트 읽기/쓰기.

모든 건강 데이터는 이 모듈을 통해 vault(로컬 폴더)의 마크다운 노트로만 저장된다.
노트는 YAML frontmatter + 본문 형식으로 Obsidian/Dataview와 호환된다.
"""
from __future__ import annotations

import copy
import datetime as dt
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

FAMILY_DIR = "00-가족"
MEMBERS_DIR = "구성원"
EXPORT_DIR = "90-내보내기"
FAMILY_FILE = "가족구성.md"
HISTORY_FILE = "가족력.md"
LOG_FILE = "이력.md"

KNOWN_RELATIONS = [
    "나", "부인", "남편", "아들", "딸",
    "아버지", "어머니", "장인", "장모", "형", "누나", "동생", "언니", "오빠",
    "할아버지", "할머니", "삼촌", "이모", "고모", "조카",
]


# ---------------------------------------------------------------- frontmatter

# 파싱 결과 캐시 — key: 경로, value: (mtime, size, meta, body)
# vault가 커지면 YAML 파싱이 병목이 된다(노트 2,400개에서 약 1.7초).
# 파일이 그대로면 다시 파싱하지 않는다. 옵시디안·Syncthing이 바깥에서 파일을
# 바꿔도 mtime/size가 달라지므로 자동으로 무효화된다.
_NOTE_CACHE: Dict[Path, Tuple[float, int, Dict[str, Any], str]] = {}


def clear_note_cache() -> None:
    _NOTE_CACHE.clear()


def read_note(path: Path) -> Tuple[Dict[str, Any], str]:
    """노트를 (frontmatter dict, 본문) 으로 읽는다.

    호출자가 결과를 자유롭게 변형해도 캐시가 오염되지 않도록 복사본을 준다.
    """
    try:
        st = path.stat()
        cached = _NOTE_CACHE.get(path)
        if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
            return copy.deepcopy(cached[2]), cached[3]
    except OSError:
        st = None

    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if not m:
        return {}, text
    meta = yaml.safe_load(m.group(1)) or {}
    body = text[m.end():]
    if st is not None:
        _NOTE_CACHE[path] = (st.st_mtime, st.st_size, copy.deepcopy(meta), body)
    return meta, body


def write_note(path: Path, meta: Dict[str, Any], body: str) -> None:
    """노트를 원자적으로 쓴다.

    Syncthing이 vault를 실시간 동기화하는 환경(Tab S9 ↔ 다른 기기)에서
    부분 기록된 파일이 그대로 전파되면 노트가 깨진다. 임시파일에 다 쓴 뒤
    os.replace로 교체하면 다른 프로세스는 항상 완전한 파일만 본다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    content = f"---\n{front}\n---\n\n{body.lstrip()}"
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _NOTE_CACHE.pop(path, None)   # 다음 읽기에서 새로 파싱


# ---------------------------------------------------------------- vault 구조

def init_vault(vault: Path) -> None:
    vault.mkdir(parents=True, exist_ok=True)
    (vault / FAMILY_DIR).mkdir(exist_ok=True)
    (vault / MEMBERS_DIR).mkdir(exist_ok=True)
    (vault / EXPORT_DIR).mkdir(exist_ok=True)

    family = vault / FAMILY_DIR / FAMILY_FILE
    if not family.exists():
        write_note(family, {"type": "family", "members": []},
                   "# 가족구성\n\n구성원은 `14health member add <관계호칭>` 으로 등록합니다.\n")
    history = vault / FAMILY_DIR / HISTORY_FILE
    if not history.exists():
        write_note(history, {"type": "family_history", "history": []},
                   "# 가족력\n\n`14health history add --relation 부 --disease 고혈압` 으로 추가합니다.\n")
    log = vault / FAMILY_DIR / LOG_FILE
    if not log.exists():
        log.write_text(
            "# 이력\n\n앱 작업 이력 (노션 동기화 대상 — 수치·실명 없음)\n\n"
            "| 날짜 | 대상 | 작업유형 | 제목 | 노트 |\n|---|---|---|---|---|\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------- 구성원

def load_members(vault: Path) -> List[Dict[str, Any]]:
    path = vault / FAMILY_DIR / FAMILY_FILE
    if not path.exists():
        return []
    meta, _ = read_note(path)
    return list(meta.get("members") or [])


def save_members(vault: Path, members: List[Dict[str, Any]]) -> None:
    path = vault / FAMILY_DIR / FAMILY_FILE
    rows = "\n".join(
        f"| {m.get('display') or m['relation']} | {m['relation']} "
        f"| {m.get('category', '')} | {m.get('birth_year', '')} "
        f"| {m.get('sex', '')} |"
        for m in members
    )
    body = (
        "# 가족구성\n\n| 표시명 | 관계 | 분류 | 출생연도 | 성별 |\n"
        "|---|---|---|---|---|\n" + rows + "\n"
    )
    write_note(path, {"type": "family", "members": members}, body)


def get_member(vault: Path, relation: str) -> Optional[Dict[str, Any]]:
    for m in load_members(vault):
        if m["relation"] == relation:
            return m
    return None


def add_member(vault: Path, relation: str, birth_year: int, sex: str,
               category: str = "", display: str = "") -> None:
    """구성원 등록.

    relation은 고유 키이자 폴더명(같은 관계가 여럿이면 "아들(첫째)" 처럼 구분).
    category/display는 선택 — 없으면 relation에서 추론하므로 기존 데이터도 동작한다.
    """
    members = load_members(vault)
    if any(m["relation"] == relation for m in members):
        raise SystemExit(f"이미 등록된 구성원입니다: {relation}")
    record: Dict[str, Any] = {"relation": relation, "birth_year": birth_year,
                              "sex": sex}
    if category:
        record["category"] = category
    if display and display != relation:
        record["display"] = display
    members.append(record)
    save_members(vault, members)
    member_dir = vault / MEMBERS_DIR / relation
    for sub in ("검진", "진료", "분석"):
        (member_dir / sub).mkdir(parents=True, exist_ok=True)
    profile = member_dir / "프로필.md"
    label = display or relation
    if not profile.exists():
        meta: Dict[str, Any] = {"type": "profile", "member": relation,
                                "birth_year": birth_year, "sex": sex,
                                "conditions": [], "medications": []}
        if category:
            meta["category"] = category
        if display and display != relation:
            meta["display"] = display
        write_note(
            profile, meta,
            f"# {label} 프로필\n\n- 관계: {relation}\n"
            + (f"- 분류: {category}\n" if category else "")
            + f"- 출생연도: {birth_year}\n- 성별: {sex}\n",
        )


def age_of(member: Dict[str, Any], today: Optional[dt.date] = None) -> int:
    today = today or dt.date.today()
    return max(0, today.year - int(member["birth_year"]))


# ---------------------------------------------------------------- 검진 노트

def checkup_path(vault: Path, relation: str, year: int) -> Path:
    return vault / MEMBERS_DIR / relation / "검진" / f"{year}-건강검진.md"


def add_checkup(vault: Path, relation: str, year: int,
                metrics: Dict[str, Any], memo: str = "",
                date: Optional[str] = None,
                exams: Optional[List[str]] = None) -> Path:
    if get_member(vault, relation) is None:
        raise SystemExit(f"등록되지 않은 구성원입니다: {relation} (14health member add 먼저 실행)")
    path = checkup_path(vault, relation, year)
    existing: Dict[str, Any] = {}
    existing_exams: List[str] = []
    body_memo = memo
    if path.exists():
        meta, _ = read_note(path)
        existing = dict(meta.get("metrics") or {})
        existing_exams = list(meta.get("exams") or [])
    existing.update(metrics)
    for e in (exams or []):
        if e not in existing_exams:
            existing_exams.append(e)
    meta = {
        "type": "checkup",
        "member": relation,
        "year": year,
        "date": date or f"{year}-01-01",
        "metrics": existing,
        "exams": existing_exams,
    }
    rows = "\n".join(f"| {k} | {v} |" for k, v in existing.items())
    body = f"# {relation} {year} 건강검진\n\n| 항목 | 수치 |\n|---|---|\n{rows}\n"
    if existing_exams:
        body += "\n## 시행 검진 항목\n\n" + "\n".join(f"- {e}" for e in existing_exams) + "\n"
    if body_memo:
        body += f"\n## 메모\n\n{body_memo}\n"
    write_note(path, meta, body)
    return path


def load_checkups(vault: Path, relation: str) -> List[Dict[str, Any]]:
    """구성원의 검진 노트 전체 (연도순)."""
    folder = vault / MEMBERS_DIR / relation / "검진"
    result = []
    if folder.exists():
        for f in sorted(folder.glob("*.md")):
            meta, _ = read_note(f)
            if meta.get("type") == "checkup":
                meta["_path"] = f
                result.append(meta)
    result.sort(key=lambda m: m.get("year") or 0)
    return result


# ---------------------------------------------------------------- 진료 노트

def add_visit(vault: Path, relation: str, date: str, hospital: str,
              symptoms: List[str], diagnosis: str = "",
              medications: Optional[List[str]] = None, memo: str = "",
              cost: Optional[Dict[str, int]] = None,
              claim: Optional[Dict[str, Any]] = None) -> Path:
    if get_member(vault, relation) is None:
        raise SystemExit(f"등록되지 않은 구성원입니다: {relation}")
    medications = medications or []
    cost = {k: v for k, v in (cost or {}).items() if v is not None}
    claim = {k: v for k, v in (claim or {}).items() if v not in (None, "")}
    safe_hospital = re.sub(r"[^\w가-힣]+", "-", hospital) or "진료"
    path = vault / MEMBERS_DIR / relation / "진료" / f"{date}-{safe_hospital}.md"
    n = 1
    while path.exists():
        n += 1
        path = path.with_name(f"{date}-{safe_hospital}-{n}.md")
    meta = {
        "type": "visit",
        "member": relation,
        "date": date,
        "hospital": hospital,
        "symptoms": symptoms,
        "diagnosis": diagnosis,
        "medications": medications,
    }
    if cost:
        meta["cost"] = cost
    if claim:
        meta["claim"] = claim
    body = (
        f"# {relation} 진료 — {hospital} ({date})\n\n"
        f"- 병원종류: {hospital}\n"
        f"- 증상: {', '.join(symptoms) or '-'}\n"
        f"- 진단: {diagnosis or '-'}\n"
        f"- 처방약: {', '.join(medications) or '-'}\n"
    )
    if cost:
        body += "\n## 의료비\n\n| 항목 | 금액 |\n|---|---|\n"
        body += "".join(f"| {k} | {v:,}원 |\n" for k, v in cost.items())
    if claim:
        rows = "\n".join(f"| {k} | {v:,}원 |" if k == "수령액" and isinstance(v, int)
                         else f"| {k} | {v} |" for k, v in claim.items())
        body += f"\n## 실비청구\n\n| 항목 | 내용 |\n|---|---|\n{rows}\n"
    if memo:
        body += f"\n## 메모\n\n{memo}\n"
    write_note(path, meta, body)
    return path


def load_visits(vault: Path, relation: str) -> List[Dict[str, Any]]:
    folder = vault / MEMBERS_DIR / relation / "진료"
    result = []
    if folder.exists():
        for f in sorted(folder.glob("*.md")):
            meta, _ = read_note(f)
            if meta.get("type") == "visit":
                meta["_path"] = f
                result.append(meta)
    result.sort(key=lambda m: str(m.get("date") or ""))
    return result


# ---------------------------------------------------------------- 가족력

def load_family_history(vault: Path) -> List[Dict[str, Any]]:
    path = vault / FAMILY_DIR / HISTORY_FILE
    if not path.exists():
        return []
    meta, _ = read_note(path)
    return list(meta.get("history") or [])


def add_family_history(vault: Path, relation: str, disease: str, note: str = "") -> None:
    path = vault / FAMILY_DIR / HISTORY_FILE
    history = load_family_history(vault)
    history.append({"relation": relation, "disease": disease, "note": note})
    rows = "\n".join(
        f"| {h['relation']} | {h['disease']} | {h.get('note', '')} |" for h in history
    )
    body = "# 가족력\n\n| 관계 | 질환 | 비고 |\n|---|---|---|\n" + rows + "\n"
    write_note(path, {"type": "family_history", "history": history}, body)


# ---------------------------------------------------------------- 이력 로그

def log_action(vault: Path, target: str, action: str, title: str,
               note_path: Optional[Path] = None) -> None:
    """이력 한 줄 기록. 제목에는 수치·실명을 넣지 않는다 (노션 동기화 대상)."""
    log = vault / FAMILY_DIR / LOG_FILE
    if not log.exists():
        init_vault(vault)
    link = ""
    if note_path is not None:
        rel = note_path.resolve().relative_to(vault.resolve()).as_posix()
        link = f"[[{rel.removesuffix('.md')}]]"
    date = dt.date.today().isoformat()
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"| {date} | {target} | {action} | {title} | {link} |\n")


def load_log(vault: Path) -> List[Dict[str, str]]:
    log = vault / FAMILY_DIR / LOG_FILE
    if not log.exists():
        return []
    rows = []
    for line in log.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|", line)
        if m:
            rows.append({
                "date": m.group(1).strip(),
                "target": m.group(2).strip(),
                "action": m.group(3).strip(),
                "title": m.group(4).strip(),
                "note": m.group(5).strip(),
            })
    return rows


def obsidian_uri(vault: Path, note_link: str) -> str:
    """이력의 [[링크]] → obsidian:// URI (vault 폴더명 기준)."""
    file = note_link.strip("[]")
    return (
        "obsidian://open?vault=" + urllib.parse.quote(vault.name)
        + "&file=" + urllib.parse.quote(file)
    )
