// 入力長の上限（2026-07-26 セキュリティ監査 F-7: LLM プロンプトインジェクション対策）
//
// 【正本は backend】値の正本は `backend/app/schemas.py` の
// MAX_MEMO_LEN / MAX_PRODUCT_LEN / MAX_PERIOD_LEN。上限超過の書込は API が 422
// （application/problem+json）で拒否する。フロントは同じ値で maxLength とバリデーションを
// 掛け、「1001文字目を入力して保存した瞬間に初めてサーバーエラー」になるのを防ぐ。
// backend 側の値を変更したら、このファイルも必ず合わせて更新すること。
//
// 【文字数の数え方】ブラウザの maxLength は UTF-16 コードユニット数、backend（Pydantic の
// max_length）はコードポイント数で数える。サロゲートペア（絵文字等）を含む場合は JS 側が
// 常に厳しい側へ振れるため、フロントを通過した入力が backend で 422 になることはない。

/** 結果記録の所感（staffMemo）／次回への申し送り（handoverNote）／旧 note の上限。 */
export const MAX_MEMO_LEN = 1000;

/** 案件作成の商材名（product）の上限。 */
export const MAX_PRODUCT_LEN = 100;

/** 案件作成の対象時期（targetPeriod）の上限。 */
export const MAX_PERIOD_LEN = 50;

/**
 * 上限超過時のエラーメッセージを組み立てる（超過していなければ undefined）。
 *
 * maxLength は利用者の手入力・貼り付けを抑止するが、JS で流し込んだ値（既存レコードの復元など）
 * には効かない。上限追加より前に保存された長い値を再編集して保存する経路が残るため、
 * 送信前チェックとして併用する。デザインガイド §4.2 に従い具体的な文言を返す。
 */
export function lengthError(label: string, value: string, max: number): string | undefined {
  if (value.length <= max) return undefined;
  return `${label}は${max}文字以内で入力してください（現在 ${value.length} 文字）。`;
}
