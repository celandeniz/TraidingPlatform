export function money(value: unknown) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(num);
}

export function number(value: unknown, digits = 2) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(num);
}

export function pct(value: unknown, digits = 2) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "-";
  return `${number(num, digits)}%`;
}

export function text(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}
