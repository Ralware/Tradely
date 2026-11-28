import type { Candle } from '../types/api';

export interface CandlePollResponse {
  candles?: Candle[];
  forming_candle?: Candle | null;
  forming_bar_excluded?: boolean;
}

export interface PolledCandleState {
  /** `(instrumentId, interval)` identity of the request. */
  key: string;
  /** Monotonic request sequence for this controller. */
  sequence: number;
  candles: Candle[];
  formingCandle: Candle | null;
  receivedAt: number;
}

export interface CandlePollControllerOptions {
  key: string;
  fetch: (signal: AbortSignal) => Promise<CandlePollResponse>;
  onUpdate: (state: PolledCandleState) => void;
  onError?: (error: unknown) => void;
  onContractMismatch?: (message: string) => void;
  intervalMs?: number;
  shouldPoll?: () => boolean;
  now?: () => number;
}

export interface CandlePollController {
  start(): void;
  stop(): void;
  pollOnce(): Promise<void>;
  isActive(): boolean;
}

/**
 * One-second candle poller with sequence tagging, abort-on-stop and
 * failure-safe state. It intentionally keeps the previous state when a
 * request fails; only a successful, newer response is applied.
 */
export function createCandlePollController(
  options: CandlePollControllerOptions,
): CandlePollController {
  const intervalMs = options.intervalMs ?? 1_000;
  const now = options.now ?? (() => Date.now());
  let stopped = true;
  let inFlight = false;
  let sequence = 0;
  let lastApplied = 0;
  let generation = 0;
  let controller: AbortController | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;

  const pollOnce = async (): Promise<void> => {
    if (stopped || inFlight) return;
    if (options.shouldPoll && !options.shouldPoll()) return;

    const requestGeneration = generation;
    const requestSequence = ++sequence;
    const requestController = new AbortController();
    controller = requestController;
    inFlight = true;
    try {
      const response = await options.fetch(requestController.signal);
      if (
        stopped
        || requestGeneration !== generation
        || requestSequence < lastApplied
        || requestController.signal.aborted
      ) {
        return;
      }
      if (response.forming_bar_excluded === true && !response.forming_candle) {
        options.onContractMismatch?.(
          'forming_bar_excluded=true but forming_candle is null',
        );
      }
      lastApplied = requestSequence;
      options.onUpdate({
        key: options.key,
        sequence: requestSequence,
        candles: Array.isArray(response.candles) ? response.candles : [],
        formingCandle: response.forming_candle ?? null,
        receivedAt: now(),
      });
    } catch (error) {
      if (
        stopped
        || requestGeneration !== generation
        || requestController.signal.aborted
      ) {
        return;
      }
      // Keep the last valid state. The next tick retries.
      options.onError?.(error);
    } finally {
      if (controller === requestController) {
        controller = null;
        inFlight = false;
      }
    }
  };

  return {
    start(): void {
      if (!stopped && timer !== null) return;
      generation += 1;
      sequence = 0;
      lastApplied = 0;
      stopped = false;
      void pollOnce();
      timer = setInterval(() => {
        void pollOnce();
      }, intervalMs);
    },
    stop(): void {
      stopped = true;
      generation += 1;
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
      controller?.abort();
      controller = null;
      inFlight = false;
    },
    pollOnce,
    isActive(): boolean {
      return !stopped;
    },
  };
}
