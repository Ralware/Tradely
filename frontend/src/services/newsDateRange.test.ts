import { describe, expect, it } from 'vitest';
import { getDefaultNewsDateRange, isCalendarDate, isValidNewsDateRange, localDateToApiBound } from './newsDateRange';

describe('News calendar date ranges', () => {
  it('defaults to the prior calendar month through the current local date', () => {
    expect(getDefaultNewsDateRange(new Date(2026, 10, 23, 15, 45))).toEqual({
      dateFrom: '2026-10-23', dateTo: '2026-11-23',
    });
    expect(getDefaultNewsDateRange(new Date(2026, 11, 15, 8))).toEqual({
      dateFrom: '2026-11-15', dateTo: '2026-12-15',
    });
  });

  it('clamps to the last day of the previous month, including leap years', () => {
    expect(getDefaultNewsDateRange(new Date(2027, 2, 31, 12))).toEqual({
      dateFrom: '2027-02-28', dateTo: '2027-03-31',
    });
    expect(getDefaultNewsDateRange(new Date(2028, 2, 31, 12))).toEqual({
      dateFrom: '2028-02-29', dateTo: '2028-03-31',
    });
    expect(getDefaultNewsDateRange(new Date(2027, 2, 5, 12))).toEqual({
      dateFrom: '2027-02-05', dateTo: '2027-03-05',
    });
  });

  it('converts local calendar boundaries to UTC and includes the end date through its last millisecond', () => {
    const localStart = new Date(2026, 9, 23, 0, 0, 0, 0).toISOString();
    const localEnd = new Date(2026, 10, 24, 0, 0, 0, 0);
    localEnd.setMilliseconds(localEnd.getMilliseconds() - 1);
    expect(localDateToApiBound('2026-10-23')).toBe(localStart);
    expect(localDateToApiBound('2026-11-23', true)).toBe(localEnd.toISOString().replace(/\.999Z$/, '.999999Z'));
  });

  it('rejects impossible calendar dates instead of normalizing them', () => {
    expect(isCalendarDate('2027-02-28')).toBe(true);
    expect(isCalendarDate('2027-02-29')).toBe(false);
    expect(isCalendarDate('2027-13-01')).toBe(false);
    expect(localDateToApiBound('not-a-date')).toBeUndefined();
  });

  it('accepts same-day or partially open ranges and rejects reversed or malformed ranges', () => {
    expect(isValidNewsDateRange('2026-11-23', '2026-11-23')).toBe(true);
    expect(isValidNewsDateRange('', '2026-11-23')).toBe(true);
    expect(isValidNewsDateRange('2026-11-24', '2026-11-23')).toBe(false);
    expect(isValidNewsDateRange('2026-02-30', '2026-03-01')).toBe(false);
  });
});
