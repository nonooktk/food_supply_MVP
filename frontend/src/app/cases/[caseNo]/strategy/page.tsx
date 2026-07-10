"use client";

// 画面④ 作戦シート（デザインガイド §3.4 / FR-07・FR-08・FR-09）
// 型帳票（案件情報・3ライン・過去経緯サマリ）＋ AI 交渉ポイント/シナリオ生成を分けて見せる。
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { StrategySheetPreview } from "@/components/ui/StrategySheetPreview";
import { AiGenerationPanel } from "@/components/ui/AiGenerationPanel";
import {
  generateStrategy,
  getStrategyDraft,
  getStrategySheet,
  saveStrategyDraft,
} from "@/lib/workspaceApi";
import type { StrategyDraft, StrategySheet } from "@/lib/types";

export default function StrategyPage() {
  const params = useParams<{ caseNo: string }>();
  const router = useRouter();
  const caseNo = decodeURIComponent(params.caseNo);

  const [sheet, setSheet] = useState<StrategySheet | null>(null);
  const [initialDraft, setInitialDraft] = useState<StrategyDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [notReady, setNotReady] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      const s = await getStrategySheet(caseNo);
      if (!alive) return;
      // 3ラインが未確定（②自社計画未入力）なら作戦シートは作れない
      if (s.lines.length === 0) {
        setNotReady(true);
        setLoading(false);
        return;
      }
      const d = await getStrategyDraft(caseNo);
      if (!alive) return;
      setSheet(s);
      setInitialDraft(d);
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, [caseNo]);

  const onGenerate = useCallback(() => generateStrategy(caseNo), [caseNo]);
  const onSave = useCallback(
    (draft: StrategyDraft) => saveStrategyDraft(caseNo, draft),
    [caseNo],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-400">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  if (notReady || !sheet) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-slate-900">作戦シート</h1>
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-center">
          <p className="text-sm text-amber-800">
            作戦シートの作成には、先に③3ライン算出を完了してください。
          </p>
          <div className="mt-3">
            <Button
              variant="secondary"
              onClick={() => router.push(`/cases/${encodeURIComponent(caseNo)}/lines`)}
            >
              ③ へ戻る
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900">作戦シート</h1>

      <StrategySheetPreview sheet={sheet} />

      <AiGenerationPanel onGenerate={onGenerate} onSave={onSave} initial={initialDraft} />

      <div className="flex justify-end">
        <Button onClick={() => router.push(`/cases/${encodeURIComponent(caseNo)}/result`)}>
          次へ：結果記録 →
        </Button>
      </div>
    </div>
  );
}
