"use client";

// 案件作成モーダル（デザインガイド §3.1）
// 企業・商材・提出見積・時期を入力し、保存で案件ワークスペース②へ遷移。
import { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Form";
import { api } from "@/lib/api";
import type { CaseDetail } from "@/lib/types";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: (detail: CaseDetail) => void;
}

interface FieldErrors {
  company?: string;
  product?: string;
  quotedPrice?: string;
  targetPeriod?: string;
}

export function CreateCaseModal({ open, onClose, onCreated }: Props) {
  const [company, setCompany] = useState("");
  const [product, setProduct] = useState("");
  const [quotedPrice, setQuotedPrice] = useState("");
  const [targetPeriod, setTargetPeriod] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);

  function validate(): FieldErrors {
    const e: FieldErrors = {};
    if (company.trim() === "") e.company = "取引先企業を入力してください。";
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

    setSubmitting(true);
    try {
      const detail = await api.createCase({
        company: company.trim(),
        product: product.trim(),
        quotedPrice: Number(quotedPrice),
        targetPeriod: targetPeriod.trim(),
      });
      // 入力をリセット
      setCompany("");
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
        <TextField
          label="取引先企業"
          required
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          error={errors.company}
          placeholder="例: 丸紅畜産"
        />
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
