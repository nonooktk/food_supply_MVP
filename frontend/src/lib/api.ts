// API クライアント層（実 API ⇄ モックの切替シーム）
// バックエンド（ポリゴン並行実装中・未完成）が出来るまでは NEXT_PUBLIC_USE_MOCK=true で
// モック実装が動く。実 API が揃ったら USE_MOCK=false にし、RealApi の fetch を有効化する。
//
// 画面側は必ずこの `api` 経由でデータアクセスする（fetch を画面に直書きしない）。
// これによりバックエンドの完成を待たずにフロントを先行開発できる。

import { buildThreeLineResult, calcAnnualImpact } from "@/lib/calc";
import {
  MOCK_AUTH_USER,
  MOCK_CREDENTIAL,
  MOCK_PAST_CASES,
  MOCK_RATES,
  MOCK_REASON_TAGS,
  MOCK_SUPPLIERS,
} from "@/lib/mock/data";
import * as store from "@/lib/store";
import type {
  AuthUser,
  CaseCreateInput,
  CaseDetail,
  CaseStatus,
  CompanyPlan,
  PastCase,
  PastCaseResult,
  RateInfo,
  RateManualInput,
  ReasonTag,
  ResultInput,
  ResultRecord,
  StrategyDraft,
  Supplier,
  ThreeLine,
  ThreeLineResult,
} from "@/lib/types";

/** 一覧の検索・絞り込み条件（デザインガイド §3.1 FilterBar） */
export interface CaseListFilter {
  keyword?: string;
  status?: CaseStatus | "all";
}

export interface CaseListResult {
  items: CaseDetail[];
  total: number;
}

/** フロント全体が依存する API 契約。実装（モック/実 API）を差し替え可能にする。 */
export interface Api {
  login(tenant: string, userId: string, password: string): Promise<AuthUser>;
  /** Google Identity Services の credential（IDトークン）を検証してログインする（認証シーム: google）。 */
  googleAuth(credential: string): Promise<AuthUser>;
  listCases(filter: CaseListFilter): Promise<CaseListResult>;
  listSuppliers(): Promise<Supplier[]>;
  createCase(input: CaseCreateInput): Promise<CaseDetail>;
  getCase(caseNo: string): Promise<CaseDetail>;
  getRateInfo(caseNo: string): Promise<RateInfo>;
  saveManualRate(caseNo: string, input: RateManualInput): Promise<RateInfo>;
  getPastCases(caseNo: string): Promise<PastCaseResult>;
  getCompanyPlan(caseNo: string): Promise<CompanyPlan>;
  saveCompanyPlan(caseNo: string, plan: CompanyPlan): Promise<CompanyPlan>;
  getThreeLines(caseNo: string): Promise<ThreeLineResult>;
  saveThreeLines(caseNo: string, lines: ThreeLine[]): Promise<ThreeLineResult>;
  // 画面④ 作戦シート（FR-08）。workspaceApi のシグネチャに合わせる。
  generateStrategy(caseNo: string): Promise<StrategyDraft>;
  getStrategyDraft(caseNo: string): Promise<StrategyDraft | null>;
  saveStrategyDraft(caseNo: string, draft: StrategyDraft): Promise<void>;
  // 画面⑤ 結果記録（FR-11/12/13）。workspaceApi のシグネチャに合わせる。
  getReasonTags(): Promise<ReasonTag[]>;
  getResult(caseNo: string): Promise<ResultRecord | null>;
  saveResult(caseNo: string, input: ResultInput): Promise<ResultRecord>;
}

/** ネットワーク遅延を模した待機（モックのローディング表示を確認できるように） */
function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const STATUS_LABEL: Record<CaseStatus, string> = {
  before: "交渉前",
  negotiating: "交渉中",
  done: "完了",
};

function toDetail(caseNo: string): CaseDetail {
  const summary = store.getCases().find((c) => c.caseNo === caseNo);
  const extra = store.getCaseExtra(caseNo);
  if (!summary) {
    throw new Error(`案件が見つかりません: ${caseNo}`);
  }
  return {
    ...summary,
    quotedPrice: extra.quotedPrice,
    targetPeriod: extra.targetPeriod,
    currentStep: "collect",
  };
}

/** ---- モック実装（NEXT_PUBLIC_USE_MOCK=true） ---- */
class MockApi implements Api {
  async login(tenant: string, userId: string, password: string): Promise<AuthUser> {
    await delay(400);
    const ok =
      tenant.trim() === MOCK_CREDENTIAL.tenant &&
      userId.trim() === MOCK_CREDENTIAL.userId &&
      password === MOCK_CREDENTIAL.password;
    if (!ok) {
      // 原因を推測させない一般文言（デザインガイド §3.0）
      throw new Error("テナント・ID・パスワードのいずれかが正しくありません。");
    }
    return { ...MOCK_AUTH_USER };
  }

  async googleAuth(): Promise<AuthUser> {
    // モック時は Google 検証を行わず、デモユーザーとしてログインする（開発体験のため）。
    // 実際の ID トークン検証は RealApi（NEXT_PUBLIC_USE_MOCK=false・バックエンド）で行う。
    await delay(400);
    return { ...MOCK_AUTH_USER };
  }

  async listCases(filter: CaseListFilter): Promise<CaseListResult> {
    await delay(300);
    let items = store.getCases().map((c) => {
      const extra = store.getCaseExtra(c.caseNo);
      return {
        ...c,
        quotedPrice: extra.quotedPrice,
        targetPeriod: extra.targetPeriod,
        currentStep: "collect" as const,
      };
    });

    const kw = filter.keyword?.trim();
    if (kw) {
      items = items.filter(
        (c) =>
          c.caseNo.includes(kw) ||
          c.company.includes(kw) ||
          c.product.includes(kw) ||
          c.assignee.includes(kw),
      );
    }
    if (filter.status && filter.status !== "all") {
      items = items.filter((c) => c.status === filter.status);
    }
    return { items, total: items.length };
  }

  async listSuppliers(): Promise<Supplier[]> {
    await delay(200);
    return MOCK_SUPPLIERS.map((supplier) => ({ ...supplier }));
  }

  async createCase(input: CaseCreateInput): Promise<CaseDetail> {
    await delay(400);
    const supplier = MOCK_SUPPLIERS.find((item) => item.supplierId === input.supplierId);
    if (!supplier) throw new Error("取引先が未登録です");
    const caseNo = store.nextCaseNo();
    const summary = {
      caseNo,
      company: supplier.supplierName,
      product: input.product,
      status: "before" as CaseStatus,
      updatedAt: formatToday(),
      assignee: MOCK_AUTH_USER.displayName.split(" ")[0],
    };
    store.addCase(summary, input.quotedPrice, input.targetPeriod);
    return { ...summary, quotedPrice: input.quotedPrice, targetPeriod: input.targetPeriod, currentStep: "collect" };
  }

  async getCase(caseNo: string): Promise<CaseDetail> {
    await delay(200);
    return toDetail(caseNo);
  }

  async getRateInfo(caseNo: string): Promise<RateInfo> {
    await delay(250);
    const manualRates = store.loadStore().manualRates?.[caseNo];
    if (manualRates && Object.keys(manualRates).length > 0) {
      const latestManual = Object.values(manualRates).sort((a, b) =>
        a.yearMonth.localeCompare(b.yearMonth),
      ).at(-1);
      const base = MOCK_RATES[caseNo];
      return {
        registered: true,
        latestPrice: latestManual?.priceYenKg ?? base?.latestPrice ?? null,
        currentPrice: base?.currentPrice ?? 0,
        // 手入力は前年同月比を再算出できないため未算出（null）扱い（issue #7 申し送り対応・backend と一致）。
        yoyRate: null,
        yearMonth: latestManual?.yearMonth ?? base?.yearMonth ?? null,
        source: latestManual?.source ?? null,
        inputMethod: "手入力",
        updatedAt: new Date().toISOString(),
        unit: "円/kg",
        normalizedCount: (base?.normalizedCount ?? 0) + Object.keys(manualRates).length,
        note: "手入力の相場情報を保存しました。",
      };
    }
    return (
      MOCK_RATES[caseNo] ?? {
        // 相場未登録（issue #3）: 価格0ではなく registered=false で区別する。
        registered: false,
        latestPrice: null,
        currentPrice: 0,
        yoyRate: null,
        unit: "円/kg",
        normalizedCount: 0,
        note: "相場データ未登録です。手入力または CSV 取込で登録してください。",
      }
    );
  }

  async saveManualRate(caseNo: string, input: RateManualInput): Promise<RateInfo> {
    await delay(300);
    return store.saveManualRate(caseNo, input);
  }

  async getPastCases(caseNo: string): Promise<PastCaseResult> {
    // KRE 検索は非同期・目標応答3秒以内（要件 N-04）。スケルトン表示を確認できるよう待つ。
    await delay(900);
    const staticItems = MOCK_PAST_CASES[caseNo] ?? [];

    // 判断継承（BR-10）: ⑤結果記録で決着済みの関連案件を過去経緯として合流する。
    // backend（related_past_results）と同じ意味論: 商材キー一致=direct（relation なし）、
    // 取引先キー一致（別商材）=same_supplier（グラフ補完）。
    const self = store.getCases().find((c) => c.caseNo === caseNo);
    const dynamic = self
      ? store.getPastResults(self.company, self.product, caseNo).map<PastCase>((match) => {
          const r = match.record;
          return {
            caseNo: r.caseNo,
            company: r.company,
            product: r.product,
            period: r.period,
            settledPrice: r.settledPrice,
            relation: match.relation === "direct" ? undefined : "same_supplier",
            citations: [
              {
                caseNo: r.caseNo,
                company: r.company,
                product: r.product,
                snippet: `決着 ¥${r.settledPrice.toLocaleString("ja-JP")}/kg（見積比 ${
                  r.quoteDiffPct >= 0 ? "+" : ""
                }${r.quoteDiffPct}%）。${r.note ? r.note : "所感の記録なし。"}`,
              },
            ],
          };
        })
      : [];

    const items = [...dynamic, ...staticItems];
    if (items.length === 0) {
      // 過去取引なし（過去案件・決着記録ともに無い）
      return { state: "empty", items: [] };
    }
    return { state: "ready", items };
  }

  async getCompanyPlan(caseNo: string): Promise<CompanyPlan> {
    await delay(150);
    return store.getPlan(caseNo);
  }

  async saveCompanyPlan(caseNo: string, plan: CompanyPlan): Promise<CompanyPlan> {
    await delay(300);
    store.setPlan(caseNo, plan);
    return plan;
  }

  async getThreeLines(caseNo: string): Promise<ThreeLineResult> {
    await delay(400);
    const plan = store.getPlan(caseNo);
    const rate = await this.getRateInfo(caseNo);
    const past = MOCK_PAST_CASES[caseNo] ?? [];
    const auto = buildThreeLineResult(rate, plan, past);
    // 手修正済みのラインのみ上書きする。未修正ラインは常に最新の自動算出値（auto）を使い、
    // autoValue も最新の自動算出値に保つ（「自動値に戻す」で現在の算出値へ戻せる）。
    // 年間影響額も上書き後の目標・着地で再計算する。
    const saved = store.getLines(caseNo);
    if (saved && saved.length > 0 && auto.ready) {
      const merged = auto.lines.map((l) => {
        const edit = saved.find((s) => s.type === l.type && s.isEdited);
        return edit
          ? { ...l, value: edit.value, isEdited: true, editReason: edit.editReason }
          : l;
      });
      const target = merged.find((l) => l.type === "target")?.value ?? auto.lines[0].value;
      const landing = merged.find((l) => l.type === "landing")?.value ?? auto.lines[1].value;
      const impact = calcAnnualImpact(plan, target, landing);
      return { ...auto, lines: merged, impact };
    }
    return auto;
  }

  async saveThreeLines(caseNo: string, lines: ThreeLine[]): Promise<ThreeLineResult> {
    await delay(300);
    store.setLines(caseNo, lines);
    return this.getThreeLines(caseNo);
  }

  async getStrategyDraft(caseNo: string): Promise<StrategyDraft | null> {
    await delay(150);
    return store.getStrategy(caseNo);
  }

  async saveStrategyDraft(caseNo: string, draft: StrategyDraft): Promise<void> {
    await delay(300);
    store.setStrategy(caseNo, draft);
  }

  /**
   * FR-08 交渉ポイント・シナリオの AI 生成（モックのシミュレーション）。
   * 実 AI 未接続時、過去経緯・3ラインから現実的な下書きを組み立てて返す（バックエンドと同型）。
   */
  async generateStrategy(caseNo: string): Promise<StrategyDraft> {
    await delay(900);
    const [detail, lines, past] = await Promise.all([
      this.getCase(caseNo),
      this.getThreeLines(caseNo),
      this.getPastCases(caseNo),
    ]);
    const target = lines.lines.find((l) => l.type === "target")?.value ?? detail.quotedPrice;
    const walkaway = lines.lines.find((l) => l.type === "walkaway")?.value ?? detail.quotedPrice;
    const pastItems = past.state === "ready" ? past.items : [];
    const direct = pastItems.find((p) => !p.relation);
    const neighbor = pastItems.find((p) => p.relation === "same_supplier");

    const points: StrategyDraft["points"] = [];
    points.push({
      text: `為替・相場動向を根拠に提示見積の妥当性を確認し、目標 ¥${target.toLocaleString(
        "ja-JP",
      )}/kg を起点に交渉する。撤退 ¥${walkaway.toLocaleString("ja-JP")}/kg を超える提示には応じない。`,
      citations: direct ? direct.citations : [],
    });
    if (direct) {
      points.push({
        text: `前回（${direct.caseNo}）は ¥${direct.settledPrice.toLocaleString(
          "ja-JP",
        )}/kg で決着。同水準を基準に、急な値上げには前回条件との整合を求める。`,
        citations: direct.citations,
      });
    }
    points.push({
      text: `年間発注量を背景に数量メリット・長期契約を訴求する。${
        neighbor
          ? `同一取引先の別商材（${neighbor.caseNo}・¥${neighbor.settledPrice.toLocaleString(
              "ja-JP",
            )}/kg）でも数量拡大で単価を抑えた実績がある。`
          : ""
      }`,
      citations: neighbor ? neighbor.citations : [],
    });

    const scenario =
      `${detail.company}との${detail.product}交渉。まず相場・為替を根拠に提示見積の水準を確認し、` +
      `目標 ¥${target.toLocaleString("ja-JP")}/kg を提示する。相手の値上げ要求には前回決着` +
      `${direct ? `（${direct.caseNo}・¥${direct.settledPrice.toLocaleString("ja-JP")}/kg）` : ""}` +
      `との整合を求めつつ、年間数量・長期契約を条件に単価抑制を交渉する。` +
      `撤退ライン ¥${walkaway.toLocaleString("ja-JP")}/kg を超える場合は持ち帰り再検討とする。`;

    const draft: StrategyDraft = { points, scenario };
    store.setStrategy(caseNo, draft); // 生成物を永続化（バックエンドの generate も保存する）
    return draft;
  }

  // ---- 画面⑤ 結果記録（FR-11/12/13） ----
  async getReasonTags(): Promise<ReasonTag[]> {
    await delay(100);
    return MOCK_REASON_TAGS;
  }

  async getResult(caseNo: string): Promise<ResultRecord | null> {
    await delay(150);
    return store.getResult(caseNo);
  }

  async saveResult(caseNo: string, input: ResultInput): Promise<ResultRecord> {
    await delay(400);
    const [detail, lines] = await Promise.all([this.getCase(caseNo), this.getThreeLines(caseNo)]);
    const target = lines.lines.find((l) => l.type === "target")?.value ?? detail.quotedPrice;
    const walkaway = lines.lines.find((l) => l.type === "walkaway")?.value ?? detail.quotedPrice;
    // 見積比・目標達成度（バックエンド results.py と同一式）。
    const quoteDiffPct =
      detail.quotedPrice > 0
        ? Math.round(((input.settledPrice - detail.quotedPrice) / detail.quotedPrice) * 1000) / 10
        : 0;
    const achievementPct =
      walkaway <= target
        ? input.settledPrice <= target
          ? 100
          : 0
        : Math.max(
            0,
            Math.min(100, Math.round(((walkaway - input.settledPrice) / (walkaway - target)) * 100)),
          );
    const record: ResultRecord = {
      ...input,
      caseNo,
      company: detail.company,
      product: detail.product,
      period: detail.targetPeriod,
      quoteDiffPct,
      achievementPct,
      savedAt: new Date().toISOString(),
    };
    store.setResult(caseNo, record);
    store.setCaseStatus(caseNo, "done"); // 案件を完了化（BR-10 で新案件の過去経緯に現れる）
    return record;
  }
}

/** ---- 実 API 実装（NEXT_PUBLIC_USE_MOCK=false）----
 * バックエンド（FastAPI・/api 配下・ポリゴン実装）と通信する。
 * 認証は MVP のモックヘッダー方式（X-Tenant-Id / X-User-Id）。ログインで得た AuthUser を
 * localStorage（auth.tsx と同じキー）から読み、各リクエストのヘッダーに付与する。
 * Entra（JWT）へ移行する際はここのヘッダー生成を Authorization: Bearer に差し替える。
 */
const AUTH_STORAGE_KEY = "freeradicals.auth.v1";

class RealApi implements Api {
  private base = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

  /** localStorage の AuthUser からモック認証ヘッダーを組み立てる（未ログイン時は空）。 */
  private authHeaders(): Record<string, string> {
    if (typeof window === "undefined") return {};
    try {
      const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
      if (!raw) return {};
      const u = JSON.parse(raw) as AuthUser;
      return { "X-Tenant-Id": u.tenantId, "X-User-Id": u.userId };
    } catch {
      return {};
    }
  }

  private async req<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...this.authHeaders(),
        ...(init?.headers as Record<string, string> | undefined),
      },
    });
    if (!res.ok) {
      // バックエンドは RFC7807（application/problem+json）で title を返す。
      let message = `API エラー: ${res.status}`;
      try {
        const problem = await res.json();
        if (problem?.title) message = String(problem.title);
      } catch {
        // JSON でなければステータスのみ
      }
      throw new Error(message);
    }
    return (await res.json()) as T;
  }

  login(tenant: string, userId: string, password: string): Promise<AuthUser> {
    return this.req<AuthUser>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ tenant, userId, password }),
    });
  }
  googleAuth(credential: string): Promise<AuthUser> {
    // GIS の credential をバックエンド（AUTH_MODE=google）で検証してログインする。
    return this.req<AuthUser>("/auth/google", {
      method: "POST",
      body: JSON.stringify({ credential }),
    });
  }
  listCases(filter: CaseListFilter): Promise<CaseListResult> {
    const q = new URLSearchParams();
    if (filter.keyword) q.set("keyword", filter.keyword);
    if (filter.status && filter.status !== "all") q.set("status", filter.status);
    return this.req<CaseListResult>(`/cases?${q.toString()}`);
  }
  listSuppliers(): Promise<Supplier[]> {
    return this.req<Supplier[]>("/suppliers");
  }
  createCase(input: CaseCreateInput): Promise<CaseDetail> {
    // 冪等キーで二重作成を防ぐ（再送・ダブルクリック対策）。
    const idempotencyKey =
      typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}`;
    return this.req<CaseDetail>("/cases", {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Idempotency-Key": idempotencyKey },
    });
  }
  getCase(caseNo: string): Promise<CaseDetail> {
    return this.req<CaseDetail>(`/cases/${encodeURIComponent(caseNo)}`);
  }
  getRateInfo(caseNo: string): Promise<RateInfo> {
    return this.req<RateInfo>(`/cases/${encodeURIComponent(caseNo)}/rate`);
  }
  saveManualRate(caseNo: string, input: RateManualInput): Promise<RateInfo> {
    return this.req<RateInfo>(`/cases/${encodeURIComponent(caseNo)}/rate/manual`, {
      method: "POST",
      body: JSON.stringify(input),
    });
  }
  getPastCases(caseNo: string): Promise<PastCaseResult> {
    return this.req<PastCaseResult>(`/cases/${encodeURIComponent(caseNo)}/past-cases`);
  }
  getCompanyPlan(caseNo: string): Promise<CompanyPlan> {
    return this.req<CompanyPlan>(`/cases/${encodeURIComponent(caseNo)}/plan`);
  }
  saveCompanyPlan(caseNo: string, plan: CompanyPlan): Promise<CompanyPlan> {
    return this.req<CompanyPlan>(`/cases/${encodeURIComponent(caseNo)}/plan`, {
      method: "PUT",
      body: JSON.stringify(plan),
    });
  }
  getThreeLines(caseNo: string): Promise<ThreeLineResult> {
    return this.req<ThreeLineResult>(`/cases/${encodeURIComponent(caseNo)}/three-lines`);
  }
  saveThreeLines(caseNo: string, lines: ThreeLine[]): Promise<ThreeLineResult> {
    return this.req<ThreeLineResult>(`/cases/${encodeURIComponent(caseNo)}/three-lines`, {
      method: "PUT",
      body: JSON.stringify({ lines }),
    });
  }
  generateStrategy(caseNo: string): Promise<StrategyDraft> {
    // FR-08 の AI 生成（KRE 供給の過去経緯・グラフ＋3ラインを根拠に、AI は価格を決めない）。
    return this.req<StrategyDraft>(`/cases/${encodeURIComponent(caseNo)}/strategy/generate`, {
      method: "POST",
    });
  }
  getStrategyDraft(caseNo: string): Promise<StrategyDraft | null> {
    return this.req<StrategyDraft | null>(`/cases/${encodeURIComponent(caseNo)}/strategy`);
  }
  saveStrategyDraft(caseNo: string, draft: StrategyDraft): Promise<void> {
    return this.req<void>(`/cases/${encodeURIComponent(caseNo)}/strategy`, {
      method: "PUT",
      body: JSON.stringify(draft),
    });
  }
  getReasonTags(): Promise<ReasonTag[]> {
    return this.req<ReasonTag[]>("/reasons");
  }
  getResult(caseNo: string): Promise<ResultRecord | null> {
    return this.req<ResultRecord | null>(`/cases/${encodeURIComponent(caseNo)}/result`);
  }
  saveResult(caseNo: string, input: ResultInput): Promise<ResultRecord> {
    // 冪等キーで二重記録を防ぐ。見積比・目標達成度はサーバー側で算出される。
    const idempotencyKey =
      typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}`;
    return this.req<ResultRecord>(`/cases/${encodeURIComponent(caseNo)}/result`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Idempotency-Key": idempotencyKey },
    });
  }
}

function formatToday(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${mm}/${dd}`;
}

/** USE_MOCK シーム。既定はモック（バックエンド未完成のため）。 */
const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK !== "false";

export const api: Api = USE_MOCK ? new MockApi() : new RealApi();

export { STATUS_LABEL };
