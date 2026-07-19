"""search.py — 過去経緯（画面②の過去経緯パネル・FR-03）。KRE 呼出の BFF。

- GET /cases/{case_no}/past-cases … 同一スペック/取引先の過去決着を返す。

設計 v3 §5.1 のとおり、本エンドポイントは KRE（RetrievalEngine）を DI で呼ぶ BFF。
MVP では過去経緯の実データ（決着単価等）を Repository 経由で DB から構築し、KRE スタブ
（USE_KRE_STUB=true）を契約越しに呼び出してグラフ文脈・引用元を得る（越境ゼロは KRE 契約側で
担保・§10.5(4)）。KRE 本実装が入ったら、ヒットの ref 解決に置き換える。
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.deps import get_repo, get_retrieval_engine, get_trace_id
from app.db import models as m
from app.db.repository import TenantScopedRepository
from app.errors import ApiProblem
from app.observability.logging import emit_error
from app.schemas import Citation, PastCase, PastCaseResult
from app.services.case_view import product_display
from kre.contract import RetrieveQuery, RetrieveRequest

router = APIRouter(tags=["search"])


def _build_citation(case: m.NegotiationCase, result: m.NegotiationResult, company: str, product: str) -> Citation:
    """過去案件の決着記録から引用元スニペットを組み立てる。"""
    bits = []
    if result.final_price is not None:
        bits.append(f"決着 ¥{int(result.final_price)}/kg")
    if result.staff_memo:
        bits.append(result.staff_memo)
    elif result.result_tags:
        bits.append("・".join(result.result_tags))
    # 次回への申し送り（次回案件の判断材料）を明示ラベル付きで提示（issue #6 Want）。
    if result.handover_note:
        bits.append(f"申し送り: {result.handover_note}")
    snippet = "。".join(bits) if bits else "過去の決着記録。"
    return Citation(case_no=case.case_no, company=company, product=product, snippet=snippet)


def _warm_kre(
    engine,
    tenant_id: str,
    spec_id: int,
    supplier_id: int,
    trace_id: str,
    case_no: str,
) -> None:
    """KRE 呼び出しをレスポンス送出後に実行する（表示をブロックしない）。

    過去経緯パネルの実データは DB 由来（`related_past_results`）で完結しており、この呼び出しの
    戻り値は現状使っていない。KRE 本実装（ヒットの ref 解決）が入るまでは、DI 疎通の維持と
    将来のグラフ文脈供給の布石として呼び出しだけを残す。同期経路に置くと埋め込み＋AI Search の
    往復（warm 約110ms／cold 約2.6s）が画面表示をブロックするため、BackgroundTask で裏に回す。
    障害はベストエフォートとして握り潰し、trace_id 付きで記録する（デザインガイド §3.2）。
    """
    # 【この try/except は外さないこと】本関数は BackgroundTask としてレスポンス送出「後」に
    # 実行される。ここで例外を送出すると Starlette の ASGI サイクル（バックグラウンド実行段）へ
    # 伝播し、テストの TestClient（raise_server_exceptions=True 既定）ではそれが送出例外として表面化する。
    # 契約テスト test_kre_failure_degrades_gracefully（tests/test_api_search.py）は「KRE が落ちても
    # DB 由来の過去経緯は 200/ready で返る（部分エラー耐性）」を検証しており、ここで握り潰さないと
    # 同テストが失敗する。本番でも KRE 障害がレスポンス済みの応答へ影響しないよう、必ず握り潰す。
    try:
        engine.retrieve(
            RetrieveRequest(
                tenant_id=tenant_id,
                query=RetrieveQuery(spec_id=spec_id, supplier_id=supplier_id),
            )
        )
    except Exception as exc:  # noqa: BLE001 - KRE 障害は過去経緯表示を止めない
        emit_error(
            "past_cases.kre_retrieve",
            tenant_id=tenant_id,
            trace_id=trace_id,
            error=type(exc).__name__,
            case_no=case_no,
        )


@router.get("/cases/{case_no}/past-cases", response_model=PastCaseResult)
def get_past_cases(
    case_no: str,
    background_tasks: BackgroundTasks,
    repo: TenantScopedRepository = Depends(get_repo),
    engine=Depends(get_retrieval_engine),
    trace_id: str = Depends(get_trace_id),
) -> PastCaseResult:
    """当該案件のスペック/取引先に関連する過去決着を返す。"""
    current = repo.get(m.NegotiationCase, case_no=case_no)
    if current is None:
        raise ApiProblem(404, "案件が見つかりません", detail=f"{case_no} は存在しません。")

    # KRE を契約越しに呼ぶ（DI・グラフ文脈/引用元供給。越境ゼロは KRE 側で強制）。
    # ただし戻り値は現状未使用（実データは下記 DB 由来で構築）。同期で呼ぶと埋め込み＋AI Search の
    # 往復ぶん画面表示が遅れるため、レスポンス送出後の BackgroundTask に回して表示をブロックしない
    # （引数は session 非依存の素の値のみを渡す。詳細は _warm_kre のドックストリング参照）。
    background_tasks.add_task(
        _warm_kre,
        engine,
        repo.tenant_id,
        current.spec_id,
        current.supplier_id,
        trace_id,
        case_no,
    )

    try:
        # 過去決着の実データを Repository 経由で構築（同一スペック=直接一致 / 同一取引先=グラフ補完）。
        rows = repo.related_past_results(current.spec_id, current.supplier_id, case_no)

        items: list[PastCase] = []
        for result, past in rows:
            supplier = repo.get(m.Supplier, supplier_id=past.supplier_id)
            spec = repo.get(m.ProductSpec, spec_id=past.spec_id)
            product = repo.get(m.Product, product_id=spec.product_id) if spec is not None else None
            company = supplier.supplier_name if supplier else ""
            prod_name = product_display(product, spec)

            # 同一スペックは直接一致（relation なし）、それ以外（同一取引先の別商材）はグラフ補完。
            relation = None if past.spec_id == current.spec_id else "same_supplier"
            items.append(
                PastCase(
                    case_no=past.case_no,
                    company=company,
                    product=prod_name,
                    period=past.period or "",
                    settled_price=float(result.final_price) if result.final_price is not None else 0.0,
                    citations=[_build_citation(past, result, company, prod_name)],
                    relation=relation,
                )
            )

        return PastCaseResult(state="ready" if items else "empty", items=items)
    except ApiProblem:
        raise
    except Exception as exc:  # noqa: BLE001 - 過去経緯は部分エラーを許容（デザインガイド §3.2）
        emit_error(
            "past_cases.build",
            tenant_id=repo.tenant_id,
            trace_id=trace_id,
            error=type(exc).__name__,
            case_no=case_no,
        )
        return PastCaseResult(state="error", items=[])
