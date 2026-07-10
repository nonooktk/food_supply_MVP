"use client";

// 画面③ 3ライン算出（デザインガイド §3.3 / F-05）
// ThreeLineCard × 3（目標/着地/撤退）＋ 年間影響額試算。手修正＋修正理由記録に対応。
// 算出に必要な入力（②自社計画）が不足なら、算出値の代わりに「②へ戻る」導線を出す。
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { ThreeLineCard } from "@/components/ui/ThreeLineCard";
import { Spinner } from "@/components/ui/Spinner";
import { api } from "@/lib/api";
import { toManYen } from "@/lib/calc";
import type { LineType, ThreeLine, ThreeLineResult } from "@/lib/types";

export default function LinesPage() {
  const params = useParams<{ caseNo: string }>();
  const router = useRouter();
  const caseNo = decodeURIComponent(params.caseNo);

  const [result, setResult] = useState<ThreeLineResult | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api
      .getThreeLines(caseNo)
      .then(setResult)
      .finally(() => setLoading(false));
  }, [caseNo]);

  // 3ライン算出結果（API＝外部システム）の初回取得のための意図的な effect。
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(load, [load]);

  // 手修正の保存（該当ラインを上書きして保存 → 再取得）
  async function editLine(type: LineType, value: number, reason: string) {
    if (!result) return;
    const lines: ThreeLine[] = result.lines.map((l) =>
      l.type === type ? { ...l, value, isEdited: true, editReason: reason } : l,
    );
    const next = await api.saveThreeLines(caseNo, lines);
    setResult(next);
  }

  async function resetLine(type: LineType) {
    if (!result) return;
    const lines: ThreeLine[] = result.lines.map((l) =>
      l.type === type
        ? { ...l, value: l.autoValue, isEdited: false, editReason: undefined }
        : l,
    );
    const next = await api.saveThreeLines(caseNo, lines);
    setResult(next);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-400">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  // 算出に必要な入力が不足（②自社計画未入力）
  if (!result || !result.ready) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-slate-900">3ライン算出</h1>
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-center">
          <p className="text-sm text-amber-800">
            3ラインの算出には、②情報収集の「自社計画」の入力が必要です。
          </p>
          <div className="mt-3">
            <Button
              variant="secondary"
              onClick={() => router.push(`/cases/${encodeURIComponent(caseNo)}/collect`)}
            >
              ② へ戻る
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900">3ライン算出</h1>

      {/* 3ラインカード（本アプリの顔）。等幅固定で金額の桁位置を揃える。 */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {result.lines.map((line) => (
          <ThreeLineCard
            key={line.type}
            line={line}
            onEdit={(value, reason) => editLine(line.type, value, reason)}
            onReset={() => resetLine(line.type)}
          />
        ))}
      </div>

      {/* 年間影響額試算（§3.3 AnnualImpactSummary） */}
      <section className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-slate-900">年間影響額試算</h2>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <ImpactCell label="目標達成時（対計画）" yen={result.impact.targetYen} />
          <ImpactCell label="着地時（対計画）" yen={result.impact.landingYen} />
        </div>
        <p className="mt-2 text-xs text-slate-500">
          年間影響額 =（計画仕入単価 − ライン単価）× 月次発注量 × 12
        </p>
      </section>

      <div className="flex justify-end">
        <Button
          disabled
          title="作戦シート生成は次スプリントで実装します"
        >
          次へ：作戦シート生成 →
        </Button>
      </div>
    </div>
  );
}

/** 年間影響額の1セル。プラスは emerald、マイナスは red で着色。 */
function ImpactCell({ label, yen }: { label: string; yen: number }) {
  const positive = yen >= 0;
  return (
    <div className="rounded-md bg-slate-50 px-4 py-3">
      <p className="text-sm text-slate-500">{label}</p>
      <p
        className={`num text-xl font-bold ${positive ? "text-emerald-700" : "text-red-700"}`}
      >
        {toManYen(yen)} 万円／年
      </p>
    </div>
  );
}
