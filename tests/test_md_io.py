from health14 import md_io, vault


def _setup(vault_path):
    vault.add_member(vault_path, "나", 1978, "M")
    vault.add_checkup(vault_path, "나", 2024, {"수축기혈압": 132, "체중": 78})
    vault.add_checkup(vault_path, "나", 2025, {"수축기혈압": 138, "체중": 80})
    vault.add_visit(vault_path, "나", "2026-07-01", "내과", ["기침"], "감기", ["감기약"])


def test_export_member_md(vault_path):
    _setup(vault_path)
    files = md_io.export_member_md(vault_path, "나")
    names = [f.name for f in files]
    assert "검진-2024-건강검진.md" in names
    assert "검진-2025-건강검진.md" in names
    assert any(n.startswith("진료-") for n in names)
    assert "프로필.md" in names


def test_md_roundtrip_to_new_vault(vault_path, tmp_path):
    """내보낸 md를 새 vault로 읽어와 동일 데이터 복원."""
    _setup(vault_path)
    exported = md_io.export_member_md(vault_path, "나")
    export_dir = exported[0].parent

    new_vault = tmp_path / "fresh"
    vault.init_vault(new_vault)
    vault.add_member(new_vault, "나", 1978, "M")

    results = md_io.import_md_path(new_vault, export_dir)
    saved = [r for r in results if r["saved"]]
    assert len(saved) == 3  # 검진 2 + 진료 1 (프로필은 건너뜀)

    checkups = vault.load_checkups(new_vault, "나")
    assert [c["year"] for c in checkups] == [2024, 2025]
    assert checkups[-1]["metrics"]["수축기혈압"] == 138
    visits = vault.load_visits(new_vault, "나")
    assert visits[0]["hospital"] == "내과"


def test_import_generic_md_returns_preview(vault_path):
    vault.add_member(vault_path, "나", 1978, "M")
    content = "# 2023 검진\n\n| 항목 | 수치 |\n|---|---|\n| 혈압 | 128/82 |\n| 몸무게 | 76 |\n"
    r = md_io.import_md_content(vault_path, content, relation="나")
    assert r["saved"] is False and r["kind"] == "parsed"
    assert r["data"]["metrics"]["수축기혈압"] == 128
    assert r["data"]["relation"] == "나"


def test_import_analysis_note_skipped(vault_path):
    vault.add_member(vault_path, "나", 1978, "M")
    content = "---\ntype: analysis\nmember: 나\n---\n\n| 항목 | 수치 |\n|---|---|\n| 체중 | 80 |\n"
    r = md_io.import_md_content(vault_path, content)
    assert r["saved"] is False and r["kind"] == "other"
