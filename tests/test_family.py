"""가족 관계 체계 · 관계도 · 가족정보 JSON 입출력."""
import json

import pytest

from health14 import config, family_io, relations, vault


def test_relation_categories_cover_user_list():
    keys = {c["key"] for c in relations.categories()}
    for expected in ["본인", "배우자", "부모", "처부모", "자녀", "손자", "손녀",
                     "친척", "외가친척", "배우자친척", "배우자외가"]:
        assert expected in keys, f"{expected} 카테고리 누락"


def test_relation_info_generation_and_lineage():
    assert relations.relation_info("나")["generation"] == 0
    assert relations.relation_info("아버지")["generation"] == 1
    assert relations.relation_info("손자")["generation"] == -2
    assert relations.relation_info("장인")["lineage"] == "처가"
    assert relations.relation_info("어머니")["lineage"] == "본가"


def test_relation_info_prefix_fallback():
    """같은 관계 복수 인원용 '아들(첫째)' 도 아들의 세대를 물려받는다."""
    info = relations.relation_info("아들(첫째)")
    assert info["generation"] == -1
    assert info["category"] == "자녀"


def test_relation_info_unknown_is_safe():
    info = relations.relation_info("듣도보도못한관계")
    assert info["category"] == "친척" and info["generation"] == 0


def test_display_name_backward_compatible():
    """display가 없는 기존 데이터도 그대로 동작."""
    assert relations.display_name({"relation": "나"}) == "나"
    assert relations.display_name({"relation": "아들(첫째)",
                                   "display": "큰아들"}) == "큰아들"


def _setup_family(vault_path):
    vault.add_member(vault_path, "나", 1978, "M", "본인")
    vault.add_member(vault_path, "부인", 1981, "F", "배우자")
    vault.add_member(vault_path, "아들(첫째)", 2008, "M", "자녀", "큰아들")
    vault.add_member(vault_path, "아들(둘째)", 2012, "M", "자녀", "작은아들")
    vault.add_member(vault_path, "장인", 1948, "M", "처부모")
    vault.add_family_history(vault_path, "부", "고혈압")


def test_duplicate_relation_members(vault_path):
    """같은 관계 2명이 각각 별도 폴더·표시명으로 등록된다."""
    _setup_family(vault_path)
    members = {m["relation"]: m for m in vault.load_members(vault_path)}
    assert members["아들(첫째)"]["display"] == "큰아들"
    assert members["아들(둘째)"]["display"] == "작은아들"
    assert (vault_path / vault.MEMBERS_DIR / "아들(첫째)" / "검진").is_dir()
    assert (vault_path / vault.MEMBERS_DIR / "아들(둘째)" / "검진").is_dir()


def test_family_tree_generations(vault_path):
    _setup_family(vault_path)
    tree = relations.build_family_tree(vault_path)
    gens = {g["generation"]: [m["display"] for m in g["members"]]
            for g in tree["generations"]}
    assert set(gens[0]) == {"나", "부인"}
    assert set(gens[-1]) == {"큰아들", "작은아들"}
    assert gens[1] == ["장인"]
    # 위 세대가 먼저 오도록 정렬
    order = [g["generation"] for g in tree["generations"]]
    assert order == sorted(order, reverse=True)


def test_family_tree_shows_diseases(vault_path):
    _setup_family(vault_path)
    vault.add_visit(vault_path, "나", "2026-07-25", "내과",
                    ["기침"], "급성기관지염. 경과관찰 필요", [])
    tree = relations.build_family_tree(vault_path)
    me = [m for g in tree["generations"] for m in g["members"]
          if m["relation"] == "나"][0]
    assert "급성기관지염" in me["diseases"]


def test_family_json_excludes_names_by_default(vault_path):
    _setup_family(vault_path)
    config.add_alias("홍길동", "나")
    payload = family_io.build_payload(vault_path)
    text = json.dumps(payload, ensure_ascii=False)
    assert "홍길동" not in text
    assert "aliases" not in payload


def test_family_json_includes_names_when_asked(vault_path):
    _setup_family(vault_path)
    config.add_alias("홍길동", "나")
    payload = family_io.build_payload(vault_path, include_names=True)
    assert payload["aliases"]["홍길동"] == "나"
    assert payload["contains_real_names"] is True


def test_family_json_roundtrip(vault_path, tmp_path):
    _setup_family(vault_path)
    out = family_io.export_family(vault_path, tmp_path / "가족.json")

    fresh = tmp_path / "fresh-vault"
    vault.init_vault(fresh)
    result = family_io.import_family_file(fresh, out)
    assert len(result["added"]) == 5
    assert result["history_added"] == 1

    members = {m["relation"]: m for m in vault.load_members(fresh)}
    assert members["아들(첫째)"]["display"] == "큰아들"
    assert members["장인"]["category"] == "처부모"
    assert vault.load_family_history(fresh)[0]["disease"] == "고혈압"


def test_family_json_import_skips_existing(vault_path, tmp_path):
    _setup_family(vault_path)
    out = family_io.export_family(vault_path, tmp_path / "가족.json")
    result = family_io.import_family_file(vault_path, out)   # 같은 vault에 재적용
    assert result["added"] == []
    assert len(result["skipped"]) == 5


def test_family_json_rejects_wrong_schema(vault_path):
    with pytest.raises(SystemExit):
        family_io.import_family(vault_path, {"schema": "something-else"})
