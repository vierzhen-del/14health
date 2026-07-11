import zipfile

from health14 import analysis, config, export, vault


def _setup_family(vault_path):
    vault.add_member(vault_path, "나", 1978, "M")
    vault.add_member(vault_path, "딸", 2012, "F")
    vault.add_family_history(vault_path, "부", "고혈압")
    vault.add_checkup(vault_path, "나", 2024,
                      {"수축기혈압": 132, "이완기혈압": 85, "체중": 78})
    vault.add_checkup(vault_path, "나", 2025,
                      {"수축기혈압": 138, "이완기혈압": 88, "체중": 80})


def test_checkup_roundtrip(vault_path):
    _setup_family(vault_path)
    checkups = vault.load_checkups(vault_path, "나")
    assert [c["year"] for c in checkups] == [2024, 2025]
    assert checkups[-1]["metrics"]["수축기혈압"] == 138


def test_analysis_report(vault_path):
    _setup_family(vault_path)
    report = analysis.build_member_report(vault_path, "나")
    assert report["stage"] == "중장년기"
    # 혈압 주의 + 가족력(고혈압) 가중
    bp = [r for r in report["risks"] if r["metric"] == "수축기혈압"]
    assert bp and bp[0]["status"] == "주의" and bp[0]["family_history"]
    assert bp[0]["trend"] == "악화"
    path = analysis.write_analysis_note(vault_path, "나", report)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "위험도" in text and "권장 검진" in text


def test_log_and_parse(vault_path):
    vault.add_member(vault_path, "나", 1978, "M")
    note = vault.checkup_path(vault_path, "나", 2025)
    vault.add_checkup(vault_path, "나", 2025, {"체중": 80})
    vault.log_action(vault_path, "나", "검진입력", "2025 건강검진 입력", note)
    rows = vault.load_log(vault_path)
    assert rows[-1]["action"] == "검진입력"
    assert rows[-1]["target"] == "나"
    assert "80" not in rows[-1]["title"]  # 이력 제목에 수치 없음


def test_export_import_roundtrip(vault_path, tmp_path):
    _setup_family(vault_path)
    zip_path = export.export_vault(vault_path)
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert any("가족구성" in n for n in names)

    new_vault = tmp_path / "moved-vault"
    export.import_vault(zip_path, new_vault)
    assert config.get_vault_path() == new_vault
    assert [m["relation"] for m in vault.load_members(new_vault)] == ["나", "딸"]
    checkups = vault.load_checkups(new_vault, "나")
    assert checkups[-1]["metrics"]["체중"] == 80
