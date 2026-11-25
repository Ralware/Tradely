export function cn(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ');
}

export function formatNumber(value: number | null | undefined, maximumFractionDigits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—';
  }
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits,
    minimumFractionDigits: 0,
  }).format(value);
}

export function formatPrice(
  value: number | null | undefined,
  currency?: string | null,
  maximumFractionDigits = 2,
): string {
  const formatted = formatNumber(value, maximumFractionDigits);
  if (formatted === '—' || !currency) {
    return formatted;
  }
  return `${currency} ${formatted}`;
}

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—';
  }
  return new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatFixed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—';
  }
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

export function formatSignedFixed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—';
  }
  if (value > 0) {
    return `+${formatFixed(value, digits)}`;
  }
  if (value < 0) {
    return `−${formatFixed(Math.abs(value), digits)}`;
  }
  return formatFixed(0, digits);
}

/** Decimal places for an absolute price change, not for a quoted price. */
export function changeDigits(
  value: number | null | undefined,
  pricePrecision?: number | null,
): number {
  if (typeof pricePrecision === 'number' && Number.isFinite(pricePrecision)) {
    return Math.max(0, Math.min(12, Math.trunc(pricePrecision)));
  }
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 2;
  }
  return Math.abs(value) >= 1 ? 2 : 6;
}

export function formatPercent(
  value: number | null | undefined,
  digits = 2,
  withSign = false,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—';
  }
  const sign = withSign && value > 0 ? '+' : '';
  return `${sign}${formatFixed(value, digits)}%`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString();
}

export function formatTime(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleTimeString();
}

export function toneForNumber(value: number | null | undefined): 'positive' | 'negative' | 'neutral' {
  if (value === null || value === undefined || Number.isNaN(value) || value === 0) {
    return 'neutral';
  }
  return value > 0 ? 'positive' : 'negative';
}

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
