export interface NewsDateRange {
  dateFrom: string;
  dateTo: string;
}

function formatLocalDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function isCalendarDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const candidate = new Date(0);
  candidate.setFullYear(year, month - 1, day);
  candidate.setHours(0, 0, 0, 0);
  return candidate.getFullYear() === year
    && candidate.getMonth() === month - 1
    && candidate.getDate() === day;
}

export function isValidNewsDateRange(dateFrom: string, dateTo: string): boolean {
  if ((dateFrom && !isCalendarDate(dateFrom)) || (dateTo && !isCalendarDate(dateTo))) return false;
  return !dateFrom || !dateTo || dateFrom <= dateTo;
}

export function getDefaultNewsDateRange(now: Date = new Date()): NewsDateRange {
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const endYear = end.getFullYear();
  const endMonth = end.getMonth();
  const endDay = end.getDate();
  const startMonthDate = new Date(endYear, endMonth - 1, 1);
  const daysInPreviousMonth = new Date(endYear, endMonth, 0).getDate();
  startMonthDate.setDate(Math.min(endDay, daysInPreviousMonth));
  return { dateFrom: formatLocalDate(startMonthDate), dateTo: formatLocalDate(end) };
}

export function localDateToApiBound(value: string, endOfDay = false): string | undefined {
  if (!isCalendarDate(value)) return undefined;
  const [year, month, day] = value.split('-').map(Number);
  const boundary = new Date(0);
  boundary.setFullYear(year, month - 1, day);
  boundary.setHours(0, 0, 0, 0);
  if (!endOfDay) return boundary.toISOString();
  boundary.setDate(boundary.getDate() + 1);
  boundary.setMilliseconds(boundary.getMilliseconds() - 1);
  return boundary.toISOString().replace(/\.999Z$/, '.999999Z');
}
