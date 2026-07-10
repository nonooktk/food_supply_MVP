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
} from "@/lib/mock/data";
import * as store from "@/lib/store";
import type {
  AuthUser,
  CaseCreateInput,
  CaseDetail,
  CaseStatus,
  CompanyPlan,
  PastCaseResult,
  RateInfo,
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
  listCases(filter: CaseListFilter): Promise<CaseListResult>;
  createCase(input: CaseCreateInput): Promise<CaseDetail>;
  getCase(caseNo: string): Promise<CaseDetail>;
  getRateInfo(caseNo: string): Promise<RateInfo>;
  getPastCases(caseNo: string): Promise<PastCaseResult>;
  getCompanyPlan(caseNo: string): Promise<CompanyPlan>;
  saveCompanyPlan(caseNo: string, plan: CompanyPlan): Promise<CompanyPlan>;
  getThreeLines(caseNo: string): Promise<ThreeLineResult>;
  saveThreeLines(caseNo: string, lines: ThreeLine[]): Promise<ThreeLineResult>;
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

  async createCase(input: CaseCreateInput): Promise<CaseDetail> {
    await delay(400);
    const caseNo = store.nextCaseNo();
    const summary = {
      caseNo,
      company: input.company,
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
    return (
      MOCK_RATES[caseNo] ?? {
        latestPrice: 0,
        unit: "円/kg",
        normalizedCount: 0,
        note: "相場データ未登録です。手入力または CSV 取込で登録してください。",
      }
    );
  }

  async getPastCases(caseNo: string): Promise<PastCaseResult> {
    // KRE 検索は非同期・目標応答3秒以内（要件 N-04）。スケルトン表示を確認できるよう待つ。
    await delay(900);
    const items = MOCK_PAST_CASES[caseNo];
    if (items === undefined) {
      // このモックに登録の無い案件は空扱い（過去取引なし）
      return { state: "empty", items: [] };
    }
    if (items.length === 0) {
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
    // 手修正済みのラインがあれば上書きし、年間影響額も手修正後の値で再計算する
    const saved = store.getLines(caseNo);
    if (saved && auto.ready) {
      const merged = auto.lines.map((l) => saved.find((s) => s.type === l.type) ?? l);
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
}

/** ---- 実 API 実装（NEXT_PUBLIC_USE_MOCK=false）----
 * バックエンド（FastAPI・/api 配下）と通信する。API 未完成のため現状は雛形。
 * エンドポイントの形は要件・設計に合わせてポリゴンと擦り合わせて確定する。
 */
class RealApi implements Api {
  private base = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

  private async req<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${this.base}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
    if (!res.ok) {
      throw new Error(`API エラー: ${res.status} ${res.statusText}`);
    }
    return (await res.json()) as T;
  }

  login(tenant: string, userId: string, password: string): Promise<AuthUser> {
    return this.req<AuthUser>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ tenant, userId, password }),
    });
  }
  listCases(filter: CaseListFilter): Promise<CaseListResult> {
    const q = new URLSearchParams();
    if (filter.keyword) q.set("keyword", filter.keyword);
    if (filter.status && filter.status !== "all") q.set("status", filter.status);
    return this.req<CaseListResult>(`/cases?${q.toString()}`);
  }
  createCase(input: CaseCreateInput): Promise<CaseDetail> {
    return this.req<CaseDetail>("/cases", { method: "POST", body: JSON.stringify(input) });
  }
  getCase(caseNo: string): Promise<CaseDetail> {
    return this.req<CaseDetail>(`/cases/${encodeURIComponent(caseNo)}`);
  }
  getRateInfo(caseNo: string): Promise<RateInfo> {
    return this.req<RateInfo>(`/cases/${encodeURIComponent(caseNo)}/rate`);
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
