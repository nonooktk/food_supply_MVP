"""conftest.py — KRE 契約テスト共通の検証器とフィクスチャ。

依存を増やさない方針（backend/requirements.txt を変更しない・スコープ限定）のため、
jsonschema ライブラリは使わず、設計書 §10.3 が用いる JSON Schema のサブセット
（type / required / properties / items / enum）だけを検証する最小バリデータを同梱する。

pytest の実行は backend/ を CWD にして ``python -m pytest`` を想定（CWD が sys.path に入り
``kre`` / ``app`` を import 可能）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kre.contract import retrieve_result_json_schema
from kre.stub import FIXTURES_DIR, StubRetrievalEngine

# ------------------------------------------------------------------------------
# 最小 JSON Schema バリデータ（draft 2020-12 のサブセット・§10.3 が使う範囲のみ）
# ------------------------------------------------------------------------------
def _iter_errors(instance: Any, schema: dict, path: str = "$") -> list[str]:
    """instance が schema に適合しない箇所を列挙する。空リストなら適合。"""
    errors: list[str] = []
    schema_type = schema.get("type")

    if schema_type == "object":
        if not isinstance(instance, dict):
            errors.append(f"{path}: object を期待しましたが {type(instance).__name__} でした")
        else:
            for req in schema.get("required", []):
                if req not in instance:
                    errors.append(f"{path}: 必須プロパティ '{req}' がありません")
            for key, subschema in schema.get("properties", {}).items():
                if key in instance:
                    errors += _iter_errors(instance[key], subschema, f"{path}.{key}")
    elif schema_type == "array":
        if not isinstance(instance, list):
            errors.append(f"{path}: array を期待しましたが {type(instance).__name__} でした")
        else:
            items = schema.get("items")
            if items is not None:
                for i, element in enumerate(instance):
                    errors += _iter_errors(element, items, f"{path}[{i}]")
    elif schema_type == "string":
        if not isinstance(instance, str):
            errors.append(f"{path}: string を期待しましたが {type(instance).__name__} でした")
    elif schema_type == "number":
        # bool は int のサブクラスなので数値から除外する。
        if isinstance(instance, bool) or not isinstance(instance, (int, float)):
            errors.append(f"{path}: number を期待しましたが {type(instance).__name__} でした")
    elif schema_type == "integer":
        if isinstance(instance, bool) or not isinstance(instance, int):
            errors.append(f"{path}: integer を期待しましたが {type(instance).__name__} でした")
    elif schema_type == "boolean":
        if not isinstance(instance, bool):
            errors.append(f"{path}: boolean を期待しましたが {type(instance).__name__} でした")

    # enum は type の有無に依らず検査（§10.3 の source は type 無しの enum）。
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} は enum {schema['enum']} に含まれません")

    return errors


@pytest.fixture
def json_schema_errors():
    """(instance, schema) を受け取り不適合箇所のリストを返す検証関数を提供する。"""
    return _iter_errors


@pytest.fixture
def retrieve_result_schema() -> dict:
    """RetrieveResult の正準 JSON Schema（§10.3）。"""
    return retrieve_result_json_schema()


def _load_envelope(name: str) -> dict:
    with open(FIXTURES_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def main_envelope() -> dict:
    """代表 fixture（t-frd・鶏もも肉／丸紅畜産・§10.4 基準）のエンベロープ。"""
    return _load_envelope("chicken_thigh_marubeni.json")


@pytest.fixture
def other_envelope() -> dict:
    """越境検証用の別テナント fixture（t-acme・豚バラ肉／スターゼン）のエンベロープ。"""
    return _load_envelope("other_tenant_pork_starzen.json")


@pytest.fixture
def stub() -> StubRetrievalEngine:
    """同梱 fixtures / 既定 config で構築したスタブ。"""
    return StubRetrievalEngine.from_fixtures()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR
