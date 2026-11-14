/**
 * Base URL for the FastAPI backend.
 *
 * Empty by default: the browser calls `/api/...` on the same origin and the Vite
 * dev server proxies it to FastAPI (see vite.config.ts). Set VITE_API_BASE_URL
 * only when the frontend is hosted separately.
 */
const configuredBase = (import.meta.env.VITE_API_BASE_URL ?? '').trim();
export const API_BASE_URL = configuredBase.replace(/\/+$/, '');

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export type QueryValue = string | number | boolean | Array<string | number> | null | undefined;
export type QueryParams = Record<string, QueryValue>;

interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE';
  query?: QueryParams;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export function buildApiUrl(path: string, query?: QueryParams): string {
  const url = `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
  if (!query) {
    return url;
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        params.append(key, String(item));
      }
      continue;
    }
    params.set(key, String(value));
  }
  const serialised = params.toString();
  return serialised ? `${url}?${serialised}` : url;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? 45_000;
  let timedOut = false;
  const timeoutId = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const externalSignal = options.signal;
  const forwardAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener('abort', forwardAbort, { once: true });
    }
  }

  const hasBody = options.body !== undefined;

  try {
    const response = await fetch(buildApiUrl(path, options.query), {
      method: options.method ?? 'GET',
      headers: hasBody
        ? { Accept: 'application/json', 'Content-Type': 'application/json' }
        : { Accept: 'application/json' },
      body: hasBody ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });

    const raw = await response.text();
    let payload: unknown = null;
    if (raw) {
      try {
        payload = JSON.parse(raw) as unknown;
      } catch {
        payload = raw;
      }
    }

    if (!response.ok) {
      let detail = `HTTP ${response.status} ${response.statusText}`;
      if (isRecord(payload) && typeof payload.detail === 'string') {
        detail = payload.detail;
      }
      throw new ApiError(detail, response.status);
    }

    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      if (externalSignal?.aborted) {
        throw error;
      }
      if (timedOut) {
        throw new ApiError(
          'Request timed out. The backend or an upstream data provider did not respond in time.',
        );
      }
      throw error;
    }
    throw new ApiError(
      error instanceof Error ? error.message : 'Network request failed. Is the backend running?',
    );
  } finally {
    window.clearTimeout(timeoutId);
    externalSignal?.removeEventListener('abort', forwardAbort);
  }
}
