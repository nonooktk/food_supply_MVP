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


# ------------------------------------------------------------------------------
# 本実装（engine / graph）検証用の DB データセット
#   Azure を呼ばず、グラフ補完（同一取引先の別商材・同一変動理由の他社事例）と
#   テナント越境ゼロを検証できる最小データを、FK 有効なインメモリ SQLite に投入する。
# ------------------------------------------------------------------------------
def _seed_purchasing_dataset(session):
    """t-frd（丸紅畜産）と t-acme（越境検証用）の最小購買データを投入する。

    t-frd:
      - supplier 12 丸紅畜産 / supplier 99 東西ミート（他社事例用）
      - spec 305 鶏もも肉（ブラジル／冷凍）/ spec 306 鶏むね肉（ブラジル／冷凍・別商材用）
      - case No.500023: sup12 × spec305 × RC-03（種）
      - case No.500031: sup12 × spec306 × RC-03（同一取引先の別商材）
      - case No.500099: sup99 × spec305 × RC-03（同一変動理由の他社事例）
      - result 9021: No.500023 の決着（認めた理由 RC-03）
    t-acme:
      - supplier 44 スターゼン / spec 812 豚バラ肉 / case No.700088（越境混入検査用）
    """
    from app.db import models as m

    # 共有マスタ（変動理由）。
    session.add_all(
        [
            m.RateChangeReason(reason_id="RC-03", reason_name="飼料価格高騰", impact_direction="↑"),
            m.RateChangeReason(reason_id="RC-05", reason_name="為替変動", impact_direction="±"),
        ]
    )

    # ---- t-frd ----
    session.add(m.Tenant(tenant_id="t-frd", tenant_name="ふりぃらじかるずデモ", case_no_prefix=""))
    session.add(m.Supplier(supplier_id=12, tenant_id="t-frd", supplier_name="丸紅畜産"))
    session.add(m.Supplier(supplier_id=99, tenant_id="t-frd", supplier_name="東西ミート"))
    session.add(m.Product(product_id=1, tenant_id="t-frd", product_name="鶏もも肉", unit="kg"))
    session.add(m.Product(product_id=2, tenant_id="t-frd", product_name="鶏むね肉", unit="kg"))
    session.flush()
    session.add(
        m.ProductSpec(spec_id=305, tenant_id="t-frd", product_id=1, origin="ブラジル産", storage_type="冷凍")
    )
    session.add(
        m.ProductSpec(spec_id=306, tenant_id="t-frd", product_id=2, origin="ブラジル産", storage_type="冷凍")
    )
    session.flush()
    session.add(
        m.NegotiationCase(
            tenant_id="t-frd", case_no="No.500023", supplier_id=12, spec_id=305,
            period="2025Q3", case_type="値上げ要請", status="完了",
            current_price=620, proposed_price=635, volume_kg_month=18000,
            claimed_reasons=["RC-03"],
        )
    )
    session.add(
        m.NegotiationCase(
            tenant_id="t-frd", case_no="No.500031", supplier_id=12, spec_id=306,
            period="2025Q3", case_type="値上げ要請", status="交渉中",
            current_price=520, proposed_price=540, claimed_reasons=["RC-03"],
        )
    )
    session.add(
        m.NegotiationCase(
            tenant_id="t-frd", case_no="No.500099", supplier_id=99, spec_id=305,
            period="2025Q2", case_type="値上げ要請", status="完了",
            current_price=615, proposed_price=630, claimed_reasons=["RC-03"],
        )
    )
    session.flush()
    session.add(
        m.NegotiationResult(
            tenant_id="t-frd", case_no="No.500023", final_price=635,
            achievement=78, accepted_reasons=["RC-03"], result_tags=["相場上昇を反映"],
            staff_memo="飼料高騰を一部認め決着",
        )
    )

    # ---- t-acme（越境検査用） ----
    # 代理キー（product_id/supplier_id/spec_id）は単一 PK でテナント横断に一意。
    # t-frd と衝突しない値を用いる。
    session.add(m.Tenant(tenant_id="t-acme", tenant_name="別テナント", case_no_prefix=""))
    session.add(m.Supplier(supplier_id=44, tenant_id="t-acme", supplier_name="スターゼン"))
    session.add(m.Product(product_id=91, tenant_id="t-acme", product_name="豚バラ肉", unit="kg"))
    session.flush()
    session.add(
        m.ProductSpec(spec_id=812, tenant_id="t-acme", product_id=91, origin="デンマーク産", storage_type="冷凍")
    )
    session.flush()
    session.add(
        m.NegotiationCase(
            tenant_id="t-acme", case_no="No.700088", supplier_id=44, spec_id=812,
            period="2025Q3", case_type="値上げ要請", status="完了",
            current_price=480, proposed_price=498, claimed_reasons=["RC-05"],
        )
    )
    session.flush()
    session.commit()


@pytest.fixture
def purchasing_session(db_session):
    """購買データセットを投入済みのインメモリ DB セッション（db_session は tests/conftest.py）。"""
    _seed_purchasing_dataset(db_session)
    return db_session
