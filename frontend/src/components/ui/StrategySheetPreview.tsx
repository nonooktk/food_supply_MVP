// StrategySheetPreview（デザインガイド §3.4）
// 定型フォーマットの作戦シート。案件概要・3ライン・年間影響額・過去経緯サマリを自動流し込みで表示。
// PDF 出力は将来機能のためボタンは出さない（機能要件資料 §4）。
import type { LineType, StrategySheet } from "@/lib/types";
import { toManYen } from "@/lib/calc";

const LINE_META: Record<LineType, { label: string; cls: string }> = {
  target: { label: "目標", cls: "text-emerald-700" },
  landing: { label: "着地", cls: "text-amber-700" },
  walkaway: { label: "撤退", cls: "text-red-700" },
};

export function StrategySheetPreview({ sheet }: { sheet: StrategySheet }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-900">
        作戦シート プレビュー
        <span className="ml-2 text-sm font-normal text-slate-500">（定型フォーマット）</span>
      </h2>

      {/* 案件概要 */}
      <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
        <Row label="案件番号" value={sheet.caseNo} numeric />
        <Row label="取引先" value={sheet.company} />
        <Row label="商材" value={sheet.product} />
        <Row label="交渉時期" value={sheet.targetPeriod} />
        <Row label="提出見積" value={`¥${sheet.quotedPrice.toLocaleString("ja-JP")}/kg`} numeric />
      </dl>

      {/* 3ライン */}
      <h3 className="mt-6 text-sm font-semibold text-slate-700">3ライン</h3>
      <div className="mt-2 grid grid-cols-3 gap-3">
        {sheet.lines.map((l) => {
          const m = LINE_META[l.type];
          return (
            <div key={l.type} className="rounded-md border border-slate-200 px-3 py-2">
              <div className={`text-xs font-medium ${m.cls}`}>{m.label}</div>
              <div className={`num text-lg font-bold ${m.cls}`}>
                ¥{l.value.toLocaleString("ja-JP")}
                <span className="ml-0.5 text-xs font-normal text-slate-500">/kg</span>
              </div>
              {l.isEdited && <div className="text-[11px] text-slate-500">✎ 修正済み</div>}
            </div>
          );
        })}
      </div>

      {/* 年間影響額 */}
      <div className="mt-3 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">
        年間影響額（対計画）: 目標達成時{" "}
        <span
          className={`num font-semibold ${
            sheet.impact.targetYen >= 0 ? "text-emerald-700" : "text-red-700"
          }`}
        >
          {toManYen(sheet.impact.targetYen)} 万円/年
        </span>
        {" ／ "}着地時{" "}
        <span
          className={`num font-semibold ${
            sheet.impact.landingYen >= 0 ? "text-emerald-700" : "text-red-700"
          }`}
        >
          {toManYen(sheet.impact.landingYen)} 万円/年
        </span>
      </div>

      {/* 過去経緯サマリ */}
      <h3 className="mt-6 text-sm font-semibold text-slate-700">過去経緯サマリ</h3>
      {sheet.pastSummary.length === 0 ? (
        <p className="mt-2 text-sm text-slate-500">参照できる過去経緯はありません。</p>
      ) : (
        <ul className="mt-2 space-y-1">
          {sheet.pastSummary.map((p) => (
            <li key={p.caseNo} className="text-sm text-slate-600">
              <span className="num font-medium text-slate-700">{p.caseNo}</span>（{p.company}・
              {p.product}／{p.period}）決着{" "}
              <span className="num">¥{p.settledPrice.toLocaleString("ja-JP")}/kg</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Row({ label, value, numeric }: { label: string; value: string; numeric?: boolean }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="w-20 shrink-0 text-sm text-slate-500">{label}</dt>
      <dd className={`text-sm text-slate-800 ${numeric ? "num" : ""}`}>{value}</dd>
    </div>
  );
}
