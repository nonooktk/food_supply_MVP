"""graphrag.py — GraphRAG(KRE)評価データの「答え合わせ」ハーネス。

`app/ingest/data/graphrag_eval_v1.json`（入力30件＋期待解30件）を用いて、
投入済みデータ・検索(BFF/KRE)・判定ルールが期待解を再現できるかを採点する。

採点は3部構成:
  A) データ整備 … DB に評価入力の事実（提示/現行/相場/過去決着4件）が正しく在るか
  B) 検索（根拠再現）… GET /cases/{id}/past-cases が「GraphRAGが提示すべき根拠」
     （自案件の過去決着4件・提示・相場）を漏れなく返すか（= 再現率/recall）
  C) ルール再現 … 解定義シートの規則（S1/S2/S3/S4/S7）と 3ライン算出モデル v1.0（S5、
     本体 `services/three_lines.calc_auto_lines` をそのまま使用）で期待解と一致するか

前提（解定義シートの評価前提に合わせる）:
- 各案件は「自分の相場年月の相場」「自分の過去決着4件」で評価する。同一スペックを
  共有する他案件の決着・後続月の相場は S2/S3/S5 の入力にしない（画面の「直近相場」とは
  時点の解釈が異なる。検索(B)は全関連事実を返してよい——収集は広く、判定入力は案件基準）。
- S4 の「相場で観測された理由」は現行スキーマに置き場が無いため JSON の値で判定する
  （GraphRAG 本実装で扱う場合のデータ設計課題として結果レポートに明記）。
- 期待解はこの評価でのみ使用し、アプリの DB には投入しない。

実行例（backend/ から）:
    python -m app.eval.graphrag
結果: コンソールにサマリ、詳細は docs/GraphRAG評価結果_v1.md に出力。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import models as m
from app.db.database import get_sessionmaker
from app.main import create_app
from app.services.three_lines import PlanInputs, RateInputs, calc_auto_lines

DATA_PATH = Path(__file__).resolve().parent.parent / "ingest" / "data" / "graphrag_eval_v1.json"
REPORT_PATH = Path(__file__).resolve().parents[3] / "docs" / "GraphRAG評価結果_v1.md"

S2_THRESHOLD = 0.05  # 解定義: 相場±5%


# ==============================================================================
# 判定ルール（解定義シートの規則を忠実に実装）
# ==============================================================================
def rule_s2(proposed: float, market: float) -> str:
    """S2: >相場+5%=高い、±5%=妥当、<相場−5%=安い"""
    if proposed > market * (1 + S2_THRESHOLD):
        return "高い"
    if proposed < market * (1 - S2_THRESHOLD):
        return "安い"
    return "妥当"


def rule_s3(proposed: float, past: list[float]) -> str:
    """S3: >過去最大=超、過去最小〜最大=内、<過去最小=未満（レンジ比較）"""
    if not past:
        return "データ不足"
    if proposed > max(past):
        return "過去レンジ超"
    if proposed < min(past):
        return "過去レンジ未満"
    return "過去レンジ内"


def rule_s4(claimed: str | None, observed: str | None, yoy: float | None, source: str | None) -> str:
    """S4: 理由一致かつ前年同月比>0=裏付けあり、証拠ありで不一致/非上昇=反証あり、証拠欠損=データ不足"""
    has_evidence = bool(observed) and bool(source) and yoy is not None
    if not has_evidence:
        return "データ不足"
    if claimed and observed and claimed.strip() == observed.strip() and yoy > 0:
        return "裏付けあり"
    return "反証あり"


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    return float(str(v).replace(",", "").replace("%", ""))


def _extract_yen(text: str) -> list[int]:
    """根拠文字列 `提示¥523／相場¥480（…）／過去¥462` から金額を抜き出す。"""
    return [int(x) for x in re.findall(r"¥([\d,]+)", text or "")]


# ==============================================================================
# 評価本体
# ==============================================================================
def evaluate() -> dict:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    inputs = {r["case_id"]: r for r in payload["inputs"]}
    expected = {r["case_id"]: r for r in payload["expected"]}

    session = get_sessionmaker()()
    tenant_id = session.scalar(select(m.Tenant.tenant_id).order_by(m.Tenant.created_at))
    client = TestClient(create_app())
    headers = {"X-Tenant-Id": tenant_id, "X-User-Id": "eval"}

    # 集計器: 項目ごとの (一致数, 対象数, 不一致明細)
    score: dict[str, list] = {}

    def check(item: str, case_id: str, got, want, ok=None) -> None:
        if item not in score:
            score[item] = [0, 0, []]
        s = score[item]
        s[1] += 1
        hit = ok if ok is not None else (got == want)
        if hit:
            s[0] += 1
        else:
            s[2].append((case_id, got, want))

    for case_id, row in inputs.items():
        exp = expected[case_id]
        proposed = _num(row["V1_提示価格"])
        current = _num(row["V2_現行単価"])
        market = _num(row["V5_相場"])
        yoy = _num(row["相場前年比"])  # 小数（例 0.035）
        annual = _num(row["V11_年間数量kg"])
        own_past = [_num(row[f"過去決着{i}"]) for i in range(1, 5)]
        own_past = [p for p in own_past if p is not None]

        # ---- A) データ整備: DB に事実が在るか ----
        case = session.scalar(select(m.NegotiationCase).where(
            m.NegotiationCase.tenant_id == tenant_id, m.NegotiationCase.case_no == case_id))
        check("A_案件がDBに在る", case_id, case is not None, True)
        if case is None:
            continue
        check("A_提示価格が一致", case_id, float(case.proposed_price), proposed)
        check("A_現行単価が一致", case_id, float(case.current_price), current)

        rate_row = session.scalar(select(m.MarketRate).where(
            m.MarketRate.tenant_id == tenant_id,
            m.MarketRate.spec_id == case.spec_id,
            m.MarketRate.year_month == row["相場年月"]))
        check("A_相場(自月)がDBに在る", case_id,
              float(rate_row.price_yen_kg) if rate_row else None, market)

        db_past = session.scalars(select(m.NegotiationResult.final_price).where(
            m.NegotiationResult.tenant_id == tenant_id,
            m.NegotiationResult.case_no.in_([f"{case_id}-P{i}" for i in range(1, 5)]))).all()
        check("A_過去決着4件がDBに在る", case_id, sorted(float(p) for p in db_past), sorted(own_past))

        # ---- B) 検索（根拠再現・recall）----
        res = client.get(f"/api/cases/{case_id}/past-cases", headers=headers)
        items = res.json().get("items", []) if res.status_code == 200 else []
        got_prices = {round(it["settledPrice"]) for it in items}
        missing = [p for p in own_past if round(p) not in got_prices]
        check("B_過去決着4件を検索が返す", case_id, f"欠落{missing}" if missing else "OK", "OK")

        cited = _extract_yen(exp.get("GraphRAGが提示すべき根拠", ""))
        reproducible = {round(proposed), round(market), *(round(p) for p in own_past)}
        miss_cite = [c for c in cited if c not in reproducible]
        check("B_期待根拠の金額を再現できる", case_id,
              f"欠落{miss_cite}" if miss_cite else "OK", "OK")

        # ---- C) ルール再現 ----
        width = proposed - current
        check("S1_値上げ幅", case_id, round(width), round(_num(exp["S1_値上げ幅"])))
        check("S1_値上げ率", case_id, round(width / current, 6), round(_num(exp["S1_値上げ率"]), 6))

        check("S2_相場比較", case_id, rule_s2(proposed, market), exp["S2_相場比較"])
        check("S3_過去比較", case_id, rule_s3(proposed, own_past), exp["S3_過去比較"])
        check("S4_理由裏取り", case_id,
              rule_s4(row.get("V3_主張理由"), row.get("相場で観測された理由"), yoy, row.get("相場出典")),
              exp["S4_理由裏取り"])

        # 計画は案件行の値を使う（解定義 S5 の入力は案件自身の計画単価・許容上限）。
        # 同一(spec×期)を共有する案件同士で計画値が異なる場合、DB の CompanyPlan は
        # 1件しか持てない（先勝ち）ため、DB 参照だと他案件の計画で計算してしまう。
        # DB 側は「計画が存在するか」のみ A 項目で確認する。
        plan_row = session.scalar(select(m.CompanyPlan).where(
            m.CompanyPlan.tenant_id == tenant_id,
            m.CompanyPlan.spec_id == case.spec_id,
            m.CompanyPlan.period == case.period))
        check("A_計画(spec×期)がDBに在る", case_id, plan_row is not None, True)

        lines = calc_auto_lines(
            RateInputs(market_rate=market, current_price=current, yoy_rate=yoy),
            PlanInputs(plan_price=_num(row["V8_計画単価"]),
                       ceiling_price=_num(row["V10_許容上限"]),
                       monthly_volume=(annual or 0) / 12),
            own_past,
        )
        check("S5_目標", case_id, lines["target"], round(_num(exp["S5_目標"])))
        check("S5_着地", case_id, lines["landing"], round(_num(exp["S5_着地"])))
        check("S5_撤退", case_id, lines["walkaway"], round(_num(exp["S5_撤退"])))

        check("S7_年間影響額", case_id, round(width * annual), round(_num(exp["S7_年間影響額"])))

    session.close()
    return score


# ==============================================================================
# レポート出力
# ==============================================================================
def render_report(score: dict) -> str:
    lines = [
        "# GraphRAG評価 答え合わせ結果 v1",
        "",
        "データ: `backend/app/ingest/data/graphrag_eval_v1.json`（30案件）",
        "実行: `python -m app.eval.graphrag`（本レポートは自動生成）",
        "",
        "| 項目 | 一致 / 対象 | 一致率 |",
        "|---|---|---|",
    ]
    total_hit = total_n = 0
    for item, (hit, n, _misses) in score.items():
        total_hit += hit
        total_n += n
        lines.append(f"| {item} | {hit} / {n} | {hit / n * 100:.0f}% |")
    lines.append(f"| **合計** | **{total_hit} / {total_n}** | **{total_hit / total_n * 100:.1f}%** |")

    details = [(item, s) for item, s in score.items() if s[2]]
    if details:
        lines += ["", "## 不一致の明細", ""]
        for item, (_h, _n, misses) in details:
            lines.append(f"### {item}")
            lines.append("| case | 実際 | 期待 |")
            lines.append("|---|---|---|")
            for case_id, got, want in misses:
                lines.append(f"| {case_id} | {got} | {want} |")
            lines.append("")
    else:
        lines += ["", "不一致なし（全項目一致）。", ""]

    lines += [
        "",
        "## 前提・既知の注記",
        "- 各案件は自分の相場年月・自分の過去決着4件で判定（解定義シートの前提）。",
        "- S4「相場で観測された理由」は現行DBスキーマに置き場が無く、評価用JSONの値で判定"
        "（KRE本実装時のデータ設計課題）。",
        "- S5 の計画入力（計画単価・許容上限・数量）は案件行の値を使用。同一(spec×期)を"
        "共有し計画値が異なる案件が2件あり、現行ドメインモデル（CompanyPlan は spec×期で"
        "1件）はこれを別々に保持できない（データ設計課題として記録）。",
        "- S6 は解定義により独立解にしない。S9（最終アクション）は人の判断であり自動採点しない。",
    ]
    return "\n".join(lines)


def _main() -> None:
    score = evaluate()
    report = render_report(score)
    REPORT_PATH.write_text(report, encoding="utf-8")

    print("GraphRAG評価 答え合わせ 完了:")
    for item, (hit, n, _misses) in score.items():
        mark = "✅" if hit == n else "⚠️ "
        print(f"  {mark} {item}: {hit}/{n}")
    print(f"詳細レポート: {REPORT_PATH}")


if __name__ == "__main__":
    _main()
