"""가족 관계 체계 조회와 관계도(세대 트리) 구성.

data/relations.yaml의 카테고리·호칭·세대 정보를 읽어
- 관계호칭 → 카테고리/세대/계보 조회
- 구성원 목록 → 세대별 관계도 배치 + 주요 병명 집계
를 제공한다. 모두 오프라인 규칙 기반이다.
"""
from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List

import yaml

from health14 import vault


@lru_cache(maxsize=None)
def _load() -> Dict[str, Any]:
    ref = resources.files("health14").joinpath("data/relations.yaml")
    with ref.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def categories() -> List[Dict[str, Any]]:
    """카테고리 목록 (order 순)."""
    return sorted(_load()["categories"], key=lambda c: c.get("order", 99))


@lru_cache(maxsize=None)
def _relation_index() -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for cat in _load()["categories"]:
        for rel in cat["relations"]:
            # 먼저 등록된 카테고리를 유지 (본인/배우자/부모가 친척보다 우선)
            index.setdefault(rel["name"], {
                "name": rel["name"],
                "category": cat["key"],
                "generation": rel.get("generation", 0),
                "lineage": cat.get("lineage", "본가"),
                "sex": rel.get("sex", "any"),
            })
    return index


def all_relations() -> List[str]:
    """등록 가능한 모든 관계호칭."""
    return list(_relation_index().keys())


def relation_info(relation: str) -> Dict[str, Any]:
    """관계호칭 → {category, generation, lineage}.

    같은 관계가 여럿일 때 쓰는 "아들(첫째)" · "이모2" 같은 이름도
    가장 긴 접두 일치로 기본 호칭을 찾아 세대·계보를 그대로 물려받는다.
    """
    index = _relation_index()
    if relation in index:
        return index[relation]
    matches = [name for name in index if relation.startswith(name)]
    if matches:
        return index[max(matches, key=len)]
    return {"name": relation, "category": "친척", "generation": 0,
            "lineage": "본가", "sex": "any"}


def generation_label(generation: int) -> str:
    labels = _load().get("generation_labels", {})
    return labels.get(generation, f"{generation} 세대")


def display_name(member: Dict[str, Any]) -> str:
    """표시명 — 없으면 관계호칭 (기존 데이터 하위호환)."""
    return member.get("display") or member["relation"]


def member_category(member: Dict[str, Any]) -> str:
    """구성원의 카테고리 — 저장돼 있으면 그것, 없으면 관계호칭으로 추론."""
    return member.get("category") or relation_info(member["relation"])["category"]


# ---------------------------------------------------------------- 관계도

def _member_diseases(vault_path: Path, relation: str,
                     history: List[Dict[str, Any]]) -> List[str]:
    """구성원의 주요 병명 — 진료 진단명 + 해당 구성원 가족력."""
    diseases: List[str] = []
    for visit in vault.load_visits(vault_path, relation):
        d = (visit.get("diagnosis") or "").strip()
        # 진단명이 문장형이면 앞부분만 (예: "급성기관지염. 경과관찰 필요")
        d = d.split(".")[0].split("—")[0].strip()
        if d and d not in diseases:
            diseases.append(d)
    for h in history:
        if h.get("relation") == relation and h.get("disease") not in diseases:
            diseases.append(h["disease"])
    return diseases


def build_family_tree(vault_path: Path, max_diseases: int = 3) -> Dict[str, Any]:
    """구성원 목록 → 세대별 관계도 데이터.

    반환 {generations: [{generation, label, members: [...]}], categories: [...]}
    각 member: {relation, display, age, sex, category, lineage, diseases}
    """
    members = vault.load_members(vault_path)
    history = vault.load_family_history(vault_path)

    nodes: List[Dict[str, Any]] = []
    for m in members:
        info = relation_info(m["relation"])
        diseases = _member_diseases(vault_path, m["relation"], history)
        nodes.append({
            "relation": m["relation"],
            "display": display_name(m),
            "age": vault.age_of(m),
            "sex": m.get("sex", ""),
            "category": member_category(m),
            "lineage": m.get("lineage") or info["lineage"],
            "generation": info["generation"],
            "diseases": diseases[:max_diseases],
            "disease_count": len(diseases),
        })

    by_gen: Dict[int, List[Dict[str, Any]]] = {}
    for n in nodes:
        by_gen.setdefault(n["generation"], []).append(n)

    generations = []
    for gen in sorted(by_gen, reverse=True):      # 위 세대부터
        group = sorted(by_gen[gen], key=lambda n: (n["lineage"] != "본가",
                                                   n["display"]))
        generations.append({
            "generation": gen,
            "label": generation_label(gen),
            "members": group,
        })
    return {"generations": generations,
            "categories": [c["key"] for c in categories()]}
