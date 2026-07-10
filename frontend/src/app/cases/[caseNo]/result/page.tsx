"use client";

// 画面⑤ 結果記録（デザインガイド §3.5 / FR-11・FR-12・FR-13）
// 決着単価・見積比・達成度（自動計算）、変動理由タグ（複数選択・必須）、所感。
// 保存で案件ステータスを「完了」化し、結果は判断継承で次の同一商材×取引先案件の過去経緯に現れる。
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { TextField } from "@/components/ui/Form";
import { ReasonTagSelector } from "@/components/ui/ReasonTagSelector";
import { AchievementField, QuoteDiffField } from "@/components/ui/AutoCalcField";
import { ErrorBanner } from "@/components/ui/states";
import { api } from "@/lib/api";
import {
  calcAchievementPct,
  calcQuoteDiffPct,
  getReasonTags,
  getResult,
  saveResult,
} from "@/lib/workspaceApi";
import type { ReasonTag, ResultRecord } from "@/lib/types";

export default function ResultPage() {
  const params = useParams<{ caseNo: string }>();
  const router = useRouter();
  const caseNo = decodeURIComponent(params.caseNo);

  const [loading, setLoading] = useState(true);
  const [notReady, setNotReady] = useState(false);
  const [quoted, setQuoted] = useState(0);
  const [target, setTarget] = useState(0);
  const [walkaway, setWalkaway] = useState(0);
  const [tags, setTags] = useState<ReasonTag[]>([]);

  // フォーム状態
  const [settledPrice, setSettledPrice] = useState("");
  const [deliveryTiming, setDeliveryTiming] = useState("");
  const [paymentTerms, setPaymentTerms] = useState("");
  const [reasonCodes, setReasonCodes] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<{ settled?: string; reason?: string }>({});

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [completed, setCompleted] = useState<ResultRecord | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const [detail, lines, reasonTags, existing] = await Promise.all([
        api.getCase(caseNo),
        api.getThreeLines(caseNo),
        getReasonTags(),
        getResult(caseNo),
      ]);
      if (!alive) return;
      if (lines.lines.length === 0) {
        setNotReady(true);
        setLoading(false);
        return;
      }
      setQuoted(detail.quotedPrice);
      setTarget(lines.lines.find((l) => l.type === "target")?.value ?? detail.quotedPrice);
      setWalkaway(lines.lines.find((l) => l.type === "walkaway")?.value ?? detail.quotedPrice);
      setTags(reasonTags);
      // 既存の結果があれば入力欄に復元（再編集可能）
      if (existing) {
        setSettledPrice(String(existing.settledPrice));
        setDeliveryTiming(existing.deliveryTiming);
        setPaymentTerms(existing.paymentTerms);
        setReasonCodes(existing.reasonCodes);
        setNote(existing.note);
      }
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, [caseNo]);

  const settledNum = Number(settledPrice);
  const hasSettled = settledPrice.trim() !== "" && !Number.isNaN(settledNum) && settledNum > 0;

  // 自動計算（決着単価の入力に追従）
  const quoteDiff = useMemo(
    () => (hasSettled ? calcQuoteDiffPct(settledNum, quoted) : null),
    [hasSettled, settledNum, quoted],
  );
  const achievement = useMemo(
    () => (hasSettled ? calcAchievementPct(settledNum, target, walkaway) : null),
    [hasSettled, settledNum, target, walkaway],
  );

  const save = useCallback(async () => {
    const errs: typeof errors = {};
    if (!hasSettled) errs.settled = "決着単価を入力してください。";
    if (reasonCodes.length === 0) errs.reason = "決着理由を1つ以上選択してください。";
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;

    setSaving(true);
    setSaveError(false);
    try {
      const record = await saveResult(caseNo, {
        settledPrice: settledNum,
        deliveryTiming: deliveryTiming.trim(),
        paymentTerms: paymentTerms.trim(),
        reasonCodes,
        note: note.trim(),
      });
      setCompleted(record);
    } catch {
      setSaveError(true);
    } finally {
      setSaving(false);
    }
  }, [caseNo, hasSettled, settledNum, deliveryTiming, paymentTerms, reasonCodes, note]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-400">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  if (notReady) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-slate-900">結果記録</h1>
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-center">
          <p className="text-sm text-amber-800">
            結果記録の前に、先に③3ライン算出を完了してください。
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

  // 保存完了（案件を完了化）
  if (completed) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-slate-900">結果記録</h1>
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-6">
          <p className="text-base font-semibold text-emerald-800">
            ✓ 保存して案件を完了しました
          </p>
          <p className="mt-2 num text-sm text-emerald-700">
            決着 ¥{completed.settledPrice.toLocaleString("ja-JP")}/kg ／ 見積比{" "}
            {completed.quoteDiffPct >= 0 ? "+" : ""}
            {completed.quoteDiffPct}% ／ 達成度 {completed.achievementPct}%
          </p>
          <p className="mt-2 text-sm text-emerald-700">
            この決着結果は、次に同一商材×取引先で作成した案件の②情報収集「過去経緯」に自動で参照されます（判断継承 BR-10）。
          </p>
          <div className="mt-4">
            <Button onClick={() => router.push("/cases")}>案件一覧へ戻る</Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900">結果記録</h1>

      {saveError && (
        <ErrorBanner message="保存に失敗しました。入力内容はそのままです。もう一度お試しください。" onRetry={save} />
      )}

      {/* 決着結果 */}
      <section className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-slate-900">決着結果</h2>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <TextField
            label="決着単価（円/kg）"
            required
            numeric
            type="number"
            value={settledPrice}
            onChange={(e) => {
              setSettledPrice(e.target.value);
              if (e.target.value.trim() !== "") setErrors((p) => ({ ...p, settled: undefined }));
            }}
            error={errors.settled}
            placeholder="例: 620"
          />
          <TextField
            label="納入時期"
            value={deliveryTiming}
            onChange={(e) => setDeliveryTiming(e.target.value)}
            placeholder="例: 2026/08 納入開始"
          />
          <TextField
            label="支払条件"
            value={paymentTerms}
            onChange={(e) => setPaymentTerms(e.target.value)}
            placeholder="例: 月末締め翌月末払い"
          />
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <QuoteDiffField label="見積比（自動計算）" pct={quoteDiff ?? 0} />
          <AchievementField label="目標達成度（自動計算）" pct={achievement ?? 0} />
        </div>
        {!hasSettled && (
          <p className="mt-2 text-xs text-slate-500">
            決着単価を入力すると見積比・目標達成度が自動計算されます。
          </p>
        )}
      </section>

      {/* 決着理由 */}
      <section className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-slate-900">
          決着理由 <span className="text-red-600">*</span>
          <span className="ml-2 text-sm font-normal text-slate-500">（複数選択可）</span>
        </h2>
        <div className="mt-4">
          <ReasonTagSelector
            tags={tags}
            selected={reasonCodes}
            onChange={(codes) => {
              setReasonCodes(codes);
              if (codes.length > 0) setErrors((p) => ({ ...p, reason: undefined }));
            }}
            error={errors.reason}
          />
        </div>
      </section>

      {/* 所感・申し送り */}
      <section className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-slate-900">所感・申し送り</h2>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          className="mt-3 w-full rounded-md border border-slate-300 px-3 py-2 text-sm
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1"
          placeholder="次回への申し送り事項（任意）"
        />
      </section>

      <div className="flex justify-end">
        <Button onClick={save} loading={saving}>
          保存して案件を完了 ✓
        </Button>
      </div>
    </div>
  );
}
