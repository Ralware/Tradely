import type { DirectionMode } from '../types/api';

export interface ChartOverlayToggles {
  sma: boolean;
  ema: boolean;
  bollinger: boolean;
}

export interface VisibleLogicalRange {
  from: number;
  to: number;
}

export interface AnalyticsViewState {
  overlays: ChartOverlayToggles;
  showRsi: boolean;
  showMacd: boolean;
  tab: string;
  directionMode: DirectionMode;
  /** Last analysis selection, restored when the sidebar reopens Analytics. */
  instrumentId: string;
  interval: string;
  days: number;
  /** Persisted chart zoom/scroll, keyed by instrument + timeframe. */
  ranges: Record<string, VisibleLogicalRange>;
}

const STORAGE_KEY = 'tradely:analytics-view:v1';

const DEFAULTS: AnalyticsViewState = {
  overlays: { sma: false, ema: false, bollinger: false },
  showRsi: false,
  showMacd: false,
  tab: 'risk',
  directionMode: 'long_only',
  instrumentId: '',
  interval: '1d',
  days: 3650,
  ranges: {},
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function readStorage(): AnalyticsViewState {
  if (typeof window === 'undefined') return { ...DEFAULTS, overlays: { ...DEFAULTS.overlays }, ranges: {} };
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULTS, overlays: { ...DEFAULTS.overlays }, ranges: {} };
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) return { ...DEFAULTS, overlays: { ...DEFAULTS.overlays }, ranges: {} };
    const overlays = isRecord(parsed.overlays) ? parsed.overlays : {};
    return {
      overlays: {
        sma: overlays.sma === true,
        ema: overlays.ema === true,
        bollinger: overlays.bollinger === true,
      },
      showRsi: parsed.showRsi === true,
      showMacd: parsed.showMacd === true,
      tab: typeof parsed.tab === 'string' ? parsed.tab : DEFAULTS.tab,
      directionMode: parsed.directionMode === 'short_only'
        || parsed.directionMode === 'long_short'
        ? parsed.directionMode
        : 'long_only',
      instrumentId: typeof parsed.instrumentId === 'string' ? parsed.instrumentId : '',
      interval: typeof parsed.interval === 'string' ? parsed.interval : DEFAULTS.interval,
      days: typeof parsed.days === 'number' && Number.isFinite(parsed.days)
        ? parsed.days
        : DEFAULTS.days,
      ranges: isRecord(parsed.ranges)
        ? Object.fromEntries(
          Object.entries(parsed.ranges).filter((entry): entry is [string, VisibleLogicalRange] => {
            const value = entry[1];
            return isRecord(value)
              && typeof value.from === 'number'
              && typeof value.to === 'number'
              && Number.isFinite(value.from)
              && Number.isFinite(value.to);
          }),
        )
        : {},
    };
  } catch {
    return { ...DEFAULTS, overlays: { ...DEFAULTS.overlays }, ranges: {} };
  }
}

let state: AnalyticsViewState = readStorage();

function persist(): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Storage may be unavailable or full; the in-memory copy remains valid.
  }
}

export function rangeKey(instrumentId: string, interval: string): string {
  return `${instrumentId}\u0000${interval}`;
}

export const analyticsViewStore = {
  get(): AnalyticsViewState {
    return state;
  },

  update(partial: Partial<Omit<AnalyticsViewState, 'ranges'>>): AnalyticsViewState {
    state = { ...state, ...partial };
    persist();
    return state;
  },

  setSelection(selection: { instrumentId: string; interval: string; days: number }): void {
    if (
      state.instrumentId === selection.instrumentId
      && state.interval === selection.interval
      && state.days === selection.days
    ) {
      return;
    }
    state = { ...state, ...selection };
    persist();
  },

  getRange(instrumentId: string, interval: string): VisibleLogicalRange | null {
    return state.ranges[rangeKey(instrumentId, interval)] ?? null;
  },

  setRange(instrumentId: string, interval: string, range: VisibleLogicalRange | null): void {
    const key = rangeKey(instrumentId, interval);
    if (range === null) {
      if (!(key in state.ranges)) return;
      const ranges = { ...state.ranges };
      delete ranges[key];
      state = { ...state, ranges };
    } else {
      const current = state.ranges[key];
      if (
        current
        && Math.abs(current.from - range.from) < 0.01
        && Math.abs(current.to - range.to) < 0.01
      ) {
        return;
      }
      state = { ...state, ranges: { ...state.ranges, [key]: range } };
    }
    persist();
  },

  clear(): void {
    state = { ...DEFAULTS, overlays: { ...DEFAULTS.overlays }, ranges: {} };
    persist();
  },
};
