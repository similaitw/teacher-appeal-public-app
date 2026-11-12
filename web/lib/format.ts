/** 把 "2026-06-26T19:49:02" 這類時間顯示成 2026/6/26；無法解析時原樣顯示。 */
export function formatDataDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || "");
  if (!match) return value || "未知";
  return `${match[1]}/${Number(match[2])}/${Number(match[3])}`;
}
