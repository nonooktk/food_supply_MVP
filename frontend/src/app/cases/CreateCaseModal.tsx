"use client";

// 案件作成モーダル（デザインガイド §3.1）
// 企業・商材・提出見積・時期を入力し、保存で案件ワークスペース②へ遷移。
import { useEffect, useMemo, useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Field, TextField } from "@/components/ui/Form";
import { api } from "@/lib/api";
import type { CaseDetail, Supplier } from "@/lib/types";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: (detail: CaseDetail) => void;
}

interface FieldErrors {
  supplier?: string;
  product?: string;
  quotedPrice?: string;
  targetPeriod?: string;
}

export function CreateCaseModal({ open, onClose, onCreated }: Props) {
  const [supplierId, setSupplierId] = useState<number | null>(null);
  const [supplierQuery, setSupplierQuery] = useState("");
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [suppliersError, setSuppliersError] = useState("");
  const [product, setProduct] = useState("");
  const [quotedPrice, setQuotedPrice] = useState("");
  const [targetPeriod, setTargetPeriod] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    let active = true;
    api
      .listSuppliers()
      .then((items) => {
        if (active) {
          setSuppliers(items);
          setSuppliersError("");
        }
      })
      .catch(() => {
        if (active) setSuppliersError("取引先マスタを取得できませんでした。");
      });
    return () => {
      active = false;
    };
  }, [open]);

  const filteredSuppliers = useMemo(() => {
    const keyword = supplierQuery.trim().toLowerCase();
    if (!keyword) return suppliers;
    return suppliers.filter((supplier) =>
      [supplier.supplierName, supplier.supplierCategory, supplier.supplierMemo]
        .filter(Boolean)
        .some((value) => value!.toLowerCase().includes(keyword)),
    );
  }, [supplierQuery, suppliers]);

  function validate(): FieldErrors {
    const e: FieldErrors = {};
    if (supplierId === null) e.supplier = "登録済みの取引先候補から選択してください。";
    if (product.trim() === "") e.product = "商材を入力してください。";
    const price = Number(quotedPrice);
    if (quotedPrice.trim() === "" || Number.isNaN(price) || price <= 0)
      e.quotedPrice = "提出見積（円/kg）を正の数で入力してください。";
    if (targetPeriod.trim() === "") e.targetPeriod = "交渉時期を入力してください。";
    return e;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const errs = validate();
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;
    // validate 済みでも、非同期送信直前の契約を明示しておく。
    if (supplierId === null) return;

    setSubmitting(true);
    try {
      const detail = await api.createCase({
        supplierId,
        product: product.trim(),
        quotedPrice: Number(quotedPrice),
        targetPeriod: targetPeriod.trim(),
      });
      // 入力をリセット
      setSupplierId(null);
      setSupplierQuery("");
      setProduct("");
      setQuotedPrice("");
      setTargetPeriod("");
      setErrors({});
      onCreated(detail);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="新規案件作成">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <Field label="取引先企業" required error={errors.supplier || suppliersError} htmlFor="supplier-search">
          <div className="space-y-2">
            <input
              id="supplier-search"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={open}
              aria-controls="supplier-options"
              aria-required="true"
              aria-invalid={!!(errors.supplier || suppliersError)}
              className={`w-full rounded-md border px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1 ${
                errors.supplier || suppliersError ? "border-red-500" : "border-slate-300"
              }`}
              value={supplierQuery}
              onChange={(e) => {
                setSupplierQuery(e.target.value);
                setSupplierId(null);
              }}
              placeholder="取引先名で検索して候補から選択"
            />
            <div id="supplier-options" role="listbox" className="max-h-40 overflow-y-auto rounded-md border border-slate-200 bg-white">
              {filteredSuppliers.map((supplier) => (
                <button
                  key={supplier.supplierId}
                  type="button"
                  role="option"
                  aria-selected={supplierId === supplier.supplierId}
                  className={`block w-full px-3 py-2 text-left text-sm hover:bg-slate-50 ${
                    supplierId === supplier.supplierId ? "bg-blue-50" : ""
                  }`}
                  onClick={() => {
                    setSupplierId(supplier.supplierId);
                    setSupplierQuery(supplier.supplierName);
                    setErrors((current) => ({ ...current, supplier: undefined }));
                  }}
                >
                  <span className="block font-medium text-slate-800">{supplier.supplierName}</span>
                  {(supplier.supplierCategory || supplier.supplierMemo) && (
                    <span className="block truncate text-xs text-slate-500">
                      {[supplier.supplierCategory, supplier.supplierMemo?.slice(0, 40)].filter(Boolean).join(" — ")}
                    </span>
                  )}
                </button>
              ))}
              {!suppliersError && filteredSuppliers.length === 0 && (
                <p className="px-3 py-2 text-sm text-slate-500">一致する登録済み取引先がありません。</p>
              )}
            </div>
          </div>
        </Field>
        <TextField
          label="商材（規格含む）"
          required
          value={product}
          onChange={(e) => setProduct(e.target.value)}
          error={errors.product}
          placeholder="例: 鶏もも肉（ブラジル産・冷凍）"
        />
        <TextField
          label="提出見積（円/kg）"
          required
          numeric
          type="number"
          value={quotedPrice}
          onChange={(e) => setQuotedPrice(e.target.value)}
          error={errors.quotedPrice}
          placeholder="例: 620"
        />
        <TextField
          label="交渉時期"
          required
          value={targetPeriod}
          onChange={(e) => setTargetPeriod(e.target.value)}
          error={errors.targetPeriod}
          placeholder="例: 2026Q3"
        />

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            キャンセル
          </Button>
          <Button type="submit" loading={submitting}>
            作成して情報収集へ
          </Button>
        </div>
      </form>
    </Modal>
  );
}
