/**
 * Client mirror of the backend freshness windows. A cached IndexedDB snapshot
 * must not be treated as fresh merely because its flags were fresh when it was
 * written; the newest candle timestamp decides.
 */
const INTERVAL_SECONDS: Record<string, number> = {
  '1m': 60,
  '3m': 180,
  '5m': 300,
  '15m': 900,
  '30m': 1800,
  '45m': 2700,
  '1h': 3600,
  '2h': 7200,
  '4h': 14400,
  '6h': 21600,
  '8h': 28800,
  '12h': 43200,
  '1d': 86400,
  '3d': 259200,
  '1wk': 604800,
  '1mo': 2592000,
};

const CLOSED_MARKET_GRACE_MS = 4 * 24 * 60 * 60 * 1000;

function canonical(interval: string): string {
  if (interval === '1w') return '1wk';
  if (interval === '1M') return '1mo';
  return interval;
}

function marketClosed(market: string, now: Date): boolean {
  if (market === 'crypto') return false;
  const timeZone = market === 'india' ? 'Asia/Kolkata' : 'America/New_York';
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(now);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? '';
  const weekday = get('weekday');
  if (weekday === 'Sat' || weekday === 'Sun') return true;
  const minutes = Number(get('hour')) * 60 + Number(get('minute'));
  if (market === 'india') return minutes < 9 * 60 + 15 || minutes > 15 * 60 + 30;
  return minutes < 9 * 60 + 30 || minutes > 16 * 60;
}

export function freshnessWindowMs(
  market: string,
  interval: string,
  now: Date = new Date(),
): number {
  const id = canonical(interval);
  if (id === '1wk') return 14 * 24 * 60 * 60 * 1000;
  if (id === '1mo') return 62 * 24 * 60 * 60 * 1000;
  if (id === '1d' || id === '3d') {
    return (market === 'crypto' ? 26 : 120) * 60 * 60 * 1000;
  }
  const seconds = INTERVAL_SECONDS[id];
  if (!seconds) return (market === 'crypto' ? 48 : 120) * 60 * 60 * 1000;
  const base = Math.max(seconds * 2, 60) * 1000;
  if (market !== 'india' && market !== 'global') return base;
  if (marketClosed(market, now)) return Math.max(base, CLOSED_MARKET_GRACE_MS);
  return Math.max(base, 10 * 60 * 1000);
}

export function isTimestampFresh(
  timestamp: string | null | undefined,
  market: string,
  interval: string,
  now: Date = new Date(),
): boolean {
  if (!timestamp) return false;
  const parsed = Date.parse(timestamp);
  if (Number.isNaN(parsed)) return false;
  return now.getTime() - parsed <= freshnessWindowMs(market, interval, now);
}
