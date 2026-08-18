"""캘린더 인덱스 — 날짜·구성원·종류만 뽑는 경량 조회."""
from health14 import calendar_index, vault


def _setup(vault_path):
    vault.add_member(vault_path, "나", 1978, "M", "본인")
    vault.add_member(vault_path, "아들(첫째)", 2008, "M", "자녀", "큰아들")
    vault.add_checkup(vault_path, "나", 2025, {"체중": 80})
    vault.add_visit(vault_path, "나", "2026-03-14", "내과", ["기침"],
                    "급성기관지염", ["항생제"])
    vault.add_visit(vault_path, "나", "2026-06-02", "치과", [], "치주염", [])
    vault.add_visit(vault_path, "아들(첫째)", "2026-11-07", "이비인후과",
                    ["인후통"], "편도염", [])


def test_index_collects_all_kinds(vault_path):
    _setup(vault_path)
    entries = calendar_index.build_index(vault_path)
    kinds = {e["kind"] for e in entries}
    assert kinds == {"checkup", "visit"}
    assert len(entries) == 4


def test_index_sorted_by_date(vault_path):
    _setup(vault_path)
    dates = [e["date"] for e in calendar_index.build_index(vault_path)]
    assert dates == sorted(dates)


def test_index_uses_display_name(vault_path):
    _setup(vault_path)
    son = [e for e in calendar_index.build_index(vault_path)
           if e["relation"] == "아들(첫째)"][0]
    assert son["display"] == "큰아들"


def test_index_year_filter(vault_path):
    _setup(vault_path)
    entries = calendar_index.build_index(vault_path, year=2026)
    assert {e["year"] for e in entries} == {2026}
    assert len(entries) == 3


def test_index_week_and_month(vault_path):
    _setup(vault_path)
    visit = [e for e in calendar_index.build_index(vault_path)
             if e["date"] == "2026-03-14"][0]
    assert visit["month"] == 3
    assert visit["week"] == "2026-W11"
    assert visit["label"] == "진료"
    assert "내과" in visit["title"]


def test_checkup_without_date_uses_year(vault_path):
    """검진 노트에 date가 없어도 연도로 배치된다."""
    _setup(vault_path)
    checkup = [e for e in calendar_index.build_index(vault_path)
               if e["kind"] == "checkup"][0]
    assert checkup["year"] == 2025


def test_available_years(vault_path):
    _setup(vault_path)
    years = calendar_index.available_years(calendar_index.build_index(vault_path))
    assert years == [2026, 2025]


def test_note_path_is_relative(vault_path):
    _setup(vault_path)
    for e in calendar_index.build_index(vault_path):
        assert not e["note"].startswith("/")
        assert (vault_path / e["note"]).exists()
