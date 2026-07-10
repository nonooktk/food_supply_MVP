// フォーム部品（デザインガイド §4.2）
// ラベルは入力欄の上。必須は赤 * ＋ aria-required。エラーは入力欄直下に赤文字＋赤枠。
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { useId } from "react";

const FOCUS =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1";

/** ラベル＋エラーを扱うフィールドラッパー */
export function Field({
  label,
  required,
  error,
  hint,
  htmlFor,
  children,
}: {
  label: string;
  required?: boolean;
  error?: string;
  hint?: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="block text-sm font-medium text-slate-700">
        {label}
        {required && (
          <span className="ml-0.5 text-red-600" aria-hidden="true">
            *
          </span>
        )}
      </label>
      <div className="mt-1">{children}</div>
      {hint && !error && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  required?: boolean;
  error?: string;
  hint?: string;
  numeric?: boolean; // 数値列は tabular-nums
}

export function TextField({
  label,
  required,
  error,
  hint,
  numeric,
  className = "",
  id,
  ...rest
}: TextFieldProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <Field label={label} required={required} error={error} hint={hint} htmlFor={fieldId}>
      <input
        id={fieldId}
        aria-required={required}
        aria-invalid={!!error}
        className={`w-full rounded-md border px-3 py-2 text-sm ${FOCUS} ${
          numeric ? "num" : ""
        } ${error ? "border-red-500" : "border-slate-300"} ${className}`}
        {...rest}
      />
    </Field>
  );
}

interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  required?: boolean;
  error?: string;
  options: { value: string; label: string }[];
}

export function SelectField({
  label,
  required,
  error,
  options,
  className = "",
  id,
  ...rest
}: SelectFieldProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <Field label={label} required={required} error={error} htmlFor={fieldId}>
      <select
        id={fieldId}
        aria-required={required}
        className={`w-full rounded-md border bg-white px-3 py-2 text-sm ${FOCUS} ${
          error ? "border-red-500" : "border-slate-300"
        } ${className}`}
        {...rest}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </Field>
  );
}
