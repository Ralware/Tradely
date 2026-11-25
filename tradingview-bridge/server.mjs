#!/usr/bin/env node
/**
 * Tradely <-> TradingView bridge.
 *
 * Tradely's backend is Python; the unofficial TradingView API used here is an
 * ESM Node.js library. This process exposes the small, read-only surface
 * Tradely needs over HTTP on loopback.
 *
 * Endpoints:
 *   GET /health
 *   GET /candles?symbol=NSE:RELIANCE&timeframe=D&from=...&to=...
 *   GET /quotes?symbols=NSE:RELIANCE,BINANCE:BTCUSDT
 *   GET /symbol?symbol=NSE:RELIANCE
 *   GET /search?q=RELIANCE&limit=20
 *
 * No order execution, no account mutation, no news.
 */

import fs from "node:fs";
import http from "node:http";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  getCandles,
  getQuote,
  getQuotes,
  getSymbolInfo,
  searchMarkets,
} from "../TradingView-API/TradingView-API-main/dist/index.js";

const require = createRequire(import.meta.url);
const libraryPackage = require("../TradingView-API/TradingView-API-main/package.json");

// Load optional bridge settings from the repository-root .env. Values already
// present in the process environment win, so shells and service managers can
// override the file without editing it.
function loadEnvFile() {
  const file = path.join(
    path.dirname(fileURLToPath(import.meta.url)),
    "..",
    ".env",
  );
  let text;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch {
    return;
  }
  for (const line of text.replace(/^\uFEFF/, "").split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match || process.env[match[1]] !== undefined) continue;
    let value = match[2];
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    process.env[match[1]] = value;
  }
}

loadEnvFile();

const HOST = process.env.TRADINGVIEW_BRIDGE_HOST || "127.0.0.1";
const PORT = Number(process.env.TRADINGVIEW_BRIDGE_PORT || 8010);
const MAX_CONCURRENCY = Math.max(
  1,
  Number(process.env.TRADINGVIEW_BRIDGE_CONCURRENCY || 3),
);
const CANDLE_TIMEOUT_MS = Math.max(
  5000,
  Number(process.env.TRADINGVIEW_CANDLE_TIMEOUT_MS || 45000),
);
const CANDLE_CACHE_MS = Math.max(
  0,
  Number(process.env.TRADINGVIEW_CANDLE_CACHE_MS || 5000),
);
const QUOTE_TIMEOUT_MS = Math.max(
  5000,
  Number(process.env.TRADINGVIEW_QUOTE_TIMEOUT_MS || 25000),
);
const SYMBOL_TIMEOUT_MS = Math.max(
  5000,
  Number(process.env.TRADINGVIEW_SYMBOL_TIMEOUT_MS || 25000),
);
const SEARCH_TIMEOUT_MS = Math.max(
  5000,
  Number(process.env.TRADINGVIEW_SEARCH_TIMEOUT_MS || 20000),
);

const TIMEFRAME_SECONDS = {
  1: 60,
  3: 180,
  5: 300,
  15: 900,
  30: 1800,
  45: 2700,
  60: 3600,
  120: 7200,
  180: 10800,
  240: 14400,
  360: 21600,
  480: 28800,
  720: 43200,
  D: 86400,
  "3D": 259200,
  W: 604800,
  M: 2592000,
};

const credentials = process.env.TRADINGVIEW_SESSION
  ? {
      session: process.env.TRADINGVIEW_SESSION,
      ...(process.env.TRADINGVIEW_SIGNATURE
        ? { signature: process.env.TRADINGVIEW_SIGNATURE }
        : {}),
    }
  : undefined;

const symbolPattern = /^[A-Z0-9][A-Z0-9._:!\-]{0,79}$/;

class BridgeError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function parseSymbol(value) {
  const symbol = String(value || "")
    .trim()
    .toUpperCase();
  if (!symbol) {
    throw new BridgeError(400, "INVALID_SYMBOL", "symbol is required");
  }
  if (!symbolPattern.test(symbol)) {
    throw new BridgeError(
      400,
      "INVALID_SYMBOL",
      `invalid symbol ${JSON.stringify(symbol)}`,
    );
  }
  return symbol;
}

function parsePositiveInteger(value, name, fallback, maximum) {
  if (value === null || value === undefined || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) {
    throw new BridgeError(
      400,
      "INVALID_ARGUMENT",
      `${name} must be a positive integer`,
    );
  }
  return Math.min(parsed, maximum);
}

function parseUnixSeconds(value, name) {
  if (value === null || value === undefined || value === "") return undefined;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) {
    throw new BridgeError(
      400,
      "INVALID_ARGUMENT",
      `${name} must be Unix seconds`,
    );
  }
  return parsed;
}

function timeframeSeconds(timeframe) {
  if (Object.hasOwn(TIMEFRAME_SECONDS, timeframe))
    return TIMEFRAME_SECONDS[timeframe];
  if (/^\d+$/.test(timeframe)) return Number(timeframe) * 60;
  return TIMEFRAME_SECONDS.D;
}

function parseSymbols(value) {
  const raw = String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (!raw.length) {
    throw new BridgeError(400, "INVALID_SYMBOL", "symbols is required");
  }
  const unique = [...new Set(raw.map(parseSymbol))];
  if (unique.length > 100) {
    throw new BridgeError(
      400,
      "INVALID_ARGUMENT",
      "at most 100 symbols are allowed per request",
    );
  }
  return unique;
}

// --- Concurrency and short-lived caches -----------------------------------
let active = 0;
const waiting = [];

function release() {
  active -= 1;
  const next = waiting.shift();
  if (next) next();
}

function withSlot(operation) {
  return new Promise((resolve, reject) => {
    const run = () => {
      active += 1;
      operation().then(resolve, reject).finally(release);
    };
    if (active < MAX_CONCURRENCY) run();
    else waiting.push(run);
  });
}

const caches = new Map();

function cacheKey(...parts) {
  return parts.join("|");
}

function cached(key, ttlMs, loader) {
  const now = Date.now();
  const existing = caches.get(key);
  if (existing && existing.expires > now) return existing.value;
  const value = loader();
  caches.set(key, { value, expires: now + ttlMs });
  if (value && typeof value.then === "function") {
    value.catch(() => {
      if (caches.get(key)?.value === value) caches.delete(key);
    });
  }
  if (caches.size > 512) {
    for (const [entryKey, entry] of caches) {
      if (entry.expires <= now) caches.delete(entryKey);
    }
    while (caches.size > 512) {
      caches.delete(caches.keys().next().value);
    }
  }
  return value;
}

// --- TradingView operations ------------------------------------------------
async function candles(query) {
  const symbol = parseSymbol(query.get("symbol"));
  const timeframe = String(query.get("timeframe") || "D")
    .trim()
    .toUpperCase();
  if (!/^[0-9A-Z]{1,4}$/.test(timeframe)) {
    throw new BridgeError(400, "INVALID_ARGUMENT", "invalid timeframe");
  }
  const adjustment = String(query.get("adjustment") || "splits").toLowerCase();
  if (!["splits", "dividends", "none"].includes(adjustment)) {
    throw new BridgeError(
      400,
      "INVALID_ARGUMENT",
      "adjustment must be splits, dividends or none",
    );
  }

  const from = parseUnixSeconds(query.get("from"), "from");
  const to = parseUnixSeconds(query.get("to"), "to");
  if (from !== undefined && to !== undefined && from > to) {
    throw new BridgeError(400, "INVALID_ARGUMENT", "from must be before to");
  }

  const maxCountParam = query.get("maxCount");
  const requestedMax =
    maxCountParam === null || maxCountParam === ""
      ? undefined
      : parsePositiveInteger(maxCountParam, "maxCount", 20_000, 1_000_000);

  let count;
  let maxCount;
  if (from !== undefined) {
    const end = to ?? Math.floor(Date.now() / 1000);
    const step = timeframeSeconds(timeframe);
    maxCount =
      requestedMax ?? Math.max(1, Math.ceil((end - from) / step) + 3);
  } else {
    // A count request keeps working, but it is no longer capped at one batch.
    count = parsePositiveInteger(query.get("count"), "count", 500, 1_000_000);
    maxCount = requestedMax;
  }

  const key = cacheKey(
    "candles",
    symbol,
    timeframe,
    from ?? "",
    to ?? "",
    count ?? maxCount,
    maxCount ?? "",
    adjustment,
  );
  const result = await cached(key, CANDLE_CACHE_MS, () =>
    withSlot(() =>
      getCandles({
        symbol,
        timeframe,
        adjustment,
        ...(from !== undefined ? { from, maxCount } : { count, maxCount }),
        ...(to !== undefined ? { to } : {}),
        timeoutMs: CANDLE_TIMEOUT_MS,
        ...(credentials ? { credentials } : {}),
      }),
    ),
  );
  const requested = from !== undefined ? maxCount : count;
  return {
    symbol,
    timeframe,
    count: result.length,
    requested_count: requested,
    max_count: maxCount ?? null,
    history_truncated:
      typeof requested === "number" && result.length >= requested,
    from: from ?? null,
    to: to ?? null,
    adjustment,
    is_adjusted: adjustment !== "none",
    source: "TradingView (unofficial)",
    fetched_at: new Date().toISOString(),
    candles: result,
  };
}

async function quotes(symbols) {
  try {
    const data = await withSlot(() =>
      getQuotes({
        symbols,
        timeoutMs: QUOTE_TIMEOUT_MS,
        ...(credentials ? { credentials } : {}),
      }),
    );
    return {
      quotes: data,
      errors: {},
      requested: symbols.length,
      returned: Object.keys(data).length,
      source: "TradingView (unofficial)",
      fetched_at: new Date().toISOString(),
    };
  } catch (batchError) {
    // getQuotes rejects the whole batch if one symbol fails. Fall back to
    // independent requests so one bad listing cannot blank every quote.
    const settled = await Promise.allSettled(
      symbols.map((symbol) =>
        withSlot(() =>
          getQuote({
            symbol,
            timeoutMs: QUOTE_TIMEOUT_MS,
            ...(credentials ? { credentials } : {}),
          }),
        ),
      ),
    );
    const data = {};
    const errors = {};
    settled.forEach((outcome, index) => {
      const symbol = symbols[index];
      if (outcome.status === "fulfilled") data[symbol] = outcome.value;
      else errors[symbol] = errorMessage(outcome.reason);
    });
    if (!Object.keys(data).length) {
      throw new BridgeError(
        502,
        "UPSTREAM_QUOTE_FAILED",
        `TradingView quote request failed for every symbol: ${errorMessage(batchError)}`,
      );
    }
    return {
      quotes: data,
      errors,
      requested: symbols.length,
      returned: Object.keys(data).length,
      source: "TradingView (unofficial)",
      fetched_at: new Date().toISOString(),
    };
  }
}

async function symbolInfo(symbol) {
  const key = cacheKey("symbol", symbol);
  return cached(key, 6 * 60 * 60 * 1000, () =>
    withSlot(() =>
      getSymbolInfo({
        symbol,
        timeoutMs: SYMBOL_TIMEOUT_MS,
        ...(credentials ? { credentials } : {}),
      }),
    ),
  );
}

async function search(query) {
  const value = String(query.get("q") || "").trim();
  if (!value) throw new BridgeError(400, "INVALID_ARGUMENT", "q is required");
  if (value.length > 80)
    throw new BridgeError(400, "INVALID_ARGUMENT", "q is too long");
  const limit = parsePositiveInteger(query.get("limit"), "limit", 20, 50);
  const options = {};
  for (const name of ["type", "exchange", "country", "sector"]) {
    const option = String(query.get(name) || "").trim();
    if (option) options[name] = option;
  }
  const key = cacheKey(
    "search",
    value.toLowerCase(),
    limit,
    JSON.stringify(options),
  );
  const result = await cached(key, 5 * 60 * 1000, () =>
    withSlot(() => searchMarkets(value, options)),
  );
  return {
    query: value,
    results: result.slice(0, limit),
    source: "TradingView (unofficial)",
  };
}

// --- HTTP plumbing ---------------------------------------------------------
function errorMessage(error) {
  if (!error) return "unknown error";
  if (typeof error === "string") return error;
  if (error.message) return String(error.message);
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
  });
  response.end(body);
}

async function route(request, response) {
  const url = new URL(
    request.url || "/",
    `http://${request.headers.host || "localhost"}`,
  );
  if (request.method !== "GET") {
    throw new BridgeError(405, "METHOD_NOT_ALLOWED", "only GET is supported");
  }

  switch (url.pathname) {
    case "/health":
      return {
        status: "ok",
        service: "tradely-tradingview-bridge",
        provider: "TradingView (unofficial)",
        library: libraryPackage.name,
        version: libraryPackage.version,
        authenticated: Boolean(credentials),
        bind: `${HOST}:${PORT}`,
        checked_at: new Date().toISOString(),
      };
    case "/candles":
      return candles(url.searchParams);
    case "/quotes":
      return quotes(parseSymbols(url.searchParams.get("symbols")));
    case "/symbol": {
      const symbol = parseSymbol(url.searchParams.get("symbol"));
      return {
        symbol,
        info: await symbolInfo(symbol),
        source: "TradingView (unofficial)",
      };
    }
    case "/search":
      return search(url.searchParams);
    default:
      throw new BridgeError(
        404,
        "NOT_FOUND",
        `unknown endpoint ${url.pathname}`,
      );
  }
}

const server = http.createServer((request, response) => {
  const started = Date.now();
  route(request, response)
    .then((payload) => {
      sendJson(response, 200, payload);
      console.log(
        `${request.method} ${request.url} 200 ${Date.now() - started}ms`,
      );
    })
    .catch((error) => {
      const status = error instanceof BridgeError ? error.status : 502;
      const code = error instanceof BridgeError ? error.code : "UPSTREAM_ERROR";
      const message = errorMessage(error);
      sendJson(response, status, {
        error: { code, message, details: error?.details ?? null },
        source: "TradingView (unofficial)",
      });
      console.error(`${request.method} ${request.url} ${status} ${message}`);
    });
});

server.listen(PORT, HOST, () => {
  console.log(
    `[tradely-bridge] TradingView bridge listening on http://${HOST}:${PORT}`,
  );
  console.log(
    `[tradely-bridge] library=${libraryPackage.name}@${libraryPackage.version} ` +
      `authenticated=${Boolean(credentials)} concurrency=${MAX_CONCURRENCY}`,
  );
});

function shutdown(signal) {
  console.log(`[tradely-bridge] ${signal} received; shutting down`);
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 3000).unref();
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
