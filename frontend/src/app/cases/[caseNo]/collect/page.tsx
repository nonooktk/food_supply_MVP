"use client";

// 画面② 情報収集（デザインガイド §3.2 / F-02・F-03・F-04）
// 相場・過去経緯・自社計画を1画面に集約（3カラム横並び・タブで隠さない）。
// 過去経緯は部分エラー対応（1機能の失敗で画面全体を止めない）。
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { CitationBadge } from "@/components/ui/CitationBadge";
import { TextField } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { SkeletonCard } from "@/components/ui/states";
import { api } from "@/lib/api";
import { isPlanReady } from "@/lib/calc";
import type { CompanyPlan, PastCaseResult, RateInfo } from "@/lib/types";
import { EMPTY_PLAN } from "@/lib/mock/data";

export default function CollectPage() {
  const params = useParams<{ caseNo: string }>();
  const router = useRouter();
  const caseNo = decodeURIComponent(params.caseNo);

  const [rate, setRate] = useState<RateInfo | null>(null);
  const [plan, setPlan] = useState<CompanyPlan>(EMPTY_PLAN);
  const [planSaved, setPlanSaved] = useState(false);

  useEffect(() => {
    api.getRateInfo(caseNo).then(setRate);
    api.getCompanyPlan(caseNo).then((p) => {
      setPlan(p);
      setPlanSaved(isPlanReady(p));
    });
  }, [caseNo]);

  // 相場が「登録済み」であることを前進条件にする（価格0＝未登録ではなく registered で判定。issue #3）。
  const rateReady = !!rate && rate.registered;
  const canProceed = rateReady && isPlanReady(plan) && planSaved;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900">情報収集</h1>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <RatePanel caseNo={caseNo} rate={rate} onSaved={setRate} />
        <PastCasePanel caseNo={caseNo} />
        <PlanPanel
          caseNo={caseNo}
          plan={plan}
          onChange={(p) => {
            setPlan(p);
            setPlanSaved(false);
          }}
          onSaved={() => setPlanSaved(true)}
        />
      </div>

      <div className="flex justify-end">
        <Button
          onClick={() => router.push(`/cases/${encodeURIComponent(caseNo)}/lines`)}
          disabled={!canProceed}
          title={
            !canProceed
              ? "相場情報の確認と、自社計画の入力・保存を完了してください"
              : undefined
          }
        >
          次へ：3ライン算出 →
        </Button>
      </div>
    </div>
  );
}

/** 相場情報パネル（§3.2） */
function RatePanel({
  caseNo,
  rate,
  onSaved,
}: {
  caseNo: string;
  rate: RateInfo | null;
  onSaved: (rate: RateInfo) => void;
}) {
  const [modalOpen, setModalOpen] = useState(false);

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-900">相場情報</h2>
      {!rate ? (
        <div className="mt-4 space-y-3">
          <SkeletonCard />
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          {rate.registered ? (
            <div>
              <p className="text-sm text-slate-500">
                直近相場
                {rate.yearMonth && (
                  <span className="ml-2 text-xs text-slate-400">
                    （対象 {formatYearMonth(rate.yearMonth)}）
                  </span>
                )}
              </p>
              <p className="num text-2xl font-bold text-slate-900">
                ¥{(rate.latestPrice ?? 0).toLocaleString("ja-JP")}
                <span className="ml-1 text-sm font-normal text-slate-500">/kg</span>
              </p>
              <dl className="mt-3 space-y-1 text-xs text-slate-600">
                <RateMeta label="前年同月比" value={formatYoy(rate.yoyRate)} />
                {rate.source && <RateMeta label="出典" value={rate.source} />}
                {rate.inputMethod && <RateMeta label="入力方法" value={rate.inputMethod} />}
                {rate.updatedAt && <RateMeta label="更新日" value={formatDate(rate.updatedAt)} />}
              </dl>
            </div>
          ) : (
            // 相場未登録: 価格0として表示せず、未登録であることを明示する（issue #3）。
            <div>
              <p className="text-sm text-slate-500">直近相場</p>
              <p className="mt-1">
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-sm font-medium text-amber-700">
                  未登録
                </span>
              </p>
              <p className="mt-2 text-sm text-slate-500">
                相場データがまだ登録されていません。手入力で登録してください。
              </p>
            </div>
          )}
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={() => setModalOpen(true)}>
              手入力
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled
              title="将来機能（現在は利用できません）"
            >
              CSV取込 ⬆（将来機能）
            </Button>
          </div>
          <p className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
            取込結果: <span className="num">{rate.normalizedCount}</span>件 正規化済み
            <br />
            {rate.note}
          </p>
          <ManualRateModal
            open={modalOpen}
            caseNo={caseNo}
            onClose={() => setModalOpen(false)}
            onSaved={(updated) => {
              onSaved(updated);
              setModalOpen(false);
            }}
          />
        </div>
      )}
    </section>
  );
}

/** 相場のメタ情報1行（対象年月・出典・入力方法・更新日など） */
function RateMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="shrink-0 text-slate-400">{label}</dt>
      <dd className="text-slate-700">{value}</dd>
    </div>
  );
}

/** 'YYYY-MM' → 'YYYY年M月'（不正値はそのまま返す） */
function formatYearMonth(ym: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(ym);
  if (!m) return ym;
  return `${m[1]}年${Number(m[2])}月`;
}

/** ISO8601 → 'YYYY/MM/DD'（不正値はそのまま返す） */
function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}/${mm}/${dd}`;
}

/** 前年同月比の表示。未算出（null）は「未算出」を返す（手入力更新後など。issue #7 申し送り対応） */
function formatYoy(yoy: number | null | undefined): string {
  if (yoy === null || yoy === undefined) return "未算出";
  const pct = Math.round(yoy * 1000) / 10;
  return `${pct > 0 ? "+" : ""}${pct}%`;
}

interface RateFieldErrors {
  yearMonth?: string;
  priceYenKg?: string;
}

function ManualRateModal({
  open,
  caseNo,
  onClose,
  onSaved,
}: {
  open: boolean;
  caseNo: string;
  onClose: () => void;
  onSaved: (rate: RateInfo) => void;
}) {
  const [yearMonth, setYearMonth] = useState("");
  const [priceYenKg, setPriceYenKg] = useState("");
  const [source, setSource] = useState("");
  const [errors, setErrors] = useState<RateFieldErrors>({});
  const [submitting, setSubmitting] = useState(false);

  function validate(): RateFieldErrors {
    const next: RateFieldErrors = {};
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(yearMonth)) {
      next.yearMonth = "対象年月を YYYY-MM 形式で入力してください。";
    }
    const price = Number(priceYenKg);
    if (priceYenKg.trim() === "" || Number.isNaN(price) || price <= 0) {
      next.priceYenKg = "相場価格（円/kg）を正の数で入力してください。";
    }
    return next;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const next = validate();
    setErrors(next);
    if (Object.keys(next).length > 0) return;

    setSubmitting(true);
    try {
      const updated = await api.saveManualRate(caseNo, {
        yearMonth,
        priceYenKg: Number(priceYenKg),
        source: source.trim() || undefined,
      });
      setYearMonth("");
      setPriceYenKg("");
      setSource("");
      setErrors({});
      onSaved(updated);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="相場情報を手入力">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <TextField
          label="対象年月"
          required
          type="month"
          value={yearMonth}
          onChange={(e) => setYearMonth(e.target.value)}
          error={errors.yearMonth}
        />
        <TextField
          label="相場価格（円/kg）"
          required
          numeric
          type="number"
          min="0"
          step="any"
          value={priceYenKg}
          onChange={(e) => setPriceYenKg(e.target.value)}
          error={errors.priceYenKg}
          placeholder="例: 600"
        />
        <TextField
          label="出典"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="例: 担当者確認"
        />
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose} disabled={submitting}>
            キャンセル
          </Button>
          <Button type="submit" loading={submitting}>
            保存
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/** 過去経緯パネル（§3.2・部分エラー・空・ローディング対応。KRE スタブ相当） */
function PastCasePanel({ caseNo }: { caseNo: string }) {
  const [result, setResult] = useState<PastCaseResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    api
      .getPastCases(caseNo)
      .then(setResult)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [caseNo]);

  // 過去経緯（KRE スタブ相当・外部システム）の初回検索のための意図的な effect。
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(load, [load]);

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-900">
        過去経緯 <span className="text-sm font-normal text-slate-500">（自動参照）</span>
      </h2>

      {loading && (
        <div className="mt-4 space-y-3">
          <p role="status" aria-live="polite" className="text-sm text-slate-500">
            関連する過去案件を検索中…
          </p>
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {!loading && error && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          過去経緯の取得に失敗しました
          <div className="mt-2">
            <Button variant="secondary" size="sm" onClick={load}>
              再試行
            </Button>
          </div>
        </div>
      )}

      {!loading && !error && result?.state === "empty" && (
        <div className="mt-4">
          <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
            過去取引なし
          </span>
          <p className="mt-2 text-sm text-slate-500">
            この組み合わせでの交渉履歴はまだありません。
          </p>
        </div>
      )}

      {!loading && !error && result?.state === "ready" && (
        <ul className="mt-4 space-y-3">
          {result.items.map((pc) => (
            <li key={pc.caseNo} className="rounded-md border border-slate-200 p-3">
              <div className="flex items-center gap-2 text-sm">
                <span className="num font-medium text-slate-700">{pc.caseNo}</span>
                {pc.relation === "same_supplier" && (
                  <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-xs text-indigo-700">
                    同一取引先の別商材
                  </span>
                )}
              </div>
              <div className="text-xs text-slate-500">
                {pc.company}・{pc.product}／{pc.period}
              </div>
              <div className="mt-1 num text-sm text-slate-800">
                決着 ¥{pc.settledPrice.toLocaleString("ja-JP")}/kg
              </div>
              <div className="mt-2">
                <CitationBadge citations={pc.citations} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** 自社計画フォーム（§3.2 / F-04） */
function PlanPanel({
  caseNo,
  plan,
  onChange,
  onSaved,
}: {
  caseNo: string;
  plan: CompanyPlan;
  onChange: (p: CompanyPlan) => void;
  onSaved: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState(false);

  function num(v: string): number {
    const n = Number(v);
    return Number.isNaN(n) ? 0 : n;
  }

  async function save() {
    setSaving(true);
    setSavedMsg(false);
    try {
      await api.saveCompanyPlan(caseNo, plan);
      onSaved();
      setSavedMsg(true);
    } finally {
      setSaving(false);
    }
  }

  const ready = isPlanReady(plan);

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-900">自社計画</h2>
      <div className="mt-4 space-y-4">
        <TextField
          label="目標原価率（%）"
          numeric
          type="number"
          value={plan.targetCostRate || ""}
          onChange={(e) => onChange({ ...plan, targetCostRate: num(e.target.value) })}
        />
        <TextField
          label="計画仕入単価（円/kg）"
          required
          numeric
          type="number"
          value={plan.planPrice || ""}
          onChange={(e) => onChange({ ...plan, planPrice: num(e.target.value) })}
        />
        <TextField
          label="月次発注量（kg）"
          required
          numeric
          type="number"
          value={plan.monthlyVolume || ""}
          onChange={(e) => onChange({ ...plan, monthlyVolume: num(e.target.value) })}
        />
        <TextField
          label="許容上限（円/kg）"
          required
          numeric
          type="number"
          value={plan.ceilingPrice || ""}
          onChange={(e) => onChange({ ...plan, ceilingPrice: num(e.target.value) })}
        />
        <div className="flex items-center gap-3">
          <Button onClick={save} loading={saving} disabled={!ready}>
            保存
          </Button>
          {savedMsg && <span className="text-sm text-emerald-600">保存しました</span>}
        </div>
        {!ready && (
          <p className="text-xs text-slate-500">
            計画仕入単価・月次発注量・許容上限は3ライン算出に必要です。
          </p>
        )}
      </div>
    </section>
  );
}
