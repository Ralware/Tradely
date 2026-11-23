import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useQuotes } from '../../hooks/useQuotes';
import { portfolioService } from '../../services/portfolioService';
import type {
  AddTransactionResponse,
  Instrument,
  Position,
  Quote,
  TransactionIntent,
  TransactionPreviewResponse,
} from '../../types/api';
import { cn, formatDateTime, formatNumber } from '../../utils/format';
import {
  assetUnit,
  instrumentQuoteRef,
  isHistoricalEntry,
  newIdempotencyKey,
} from '../../utils/transaction';
import { formatAge, quoteLabel, quoteTone } from '../../utils/quotes';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';
import { Card } from '../common/Card';
import { Field, Input, Select, Textarea } from '../common/Field';
import { Notice } from '../common/States';
import { InstrumentSearch } from '../instruments/InstrumentSearch';

const sideOptions = [
  { value: 'BUY', label: 'Buy' },
  { value: 'SELL', label: 'Sell' },
  { value: 'SELL_SHORT', label: 'Sell Short' },
  { value: 'BUY_TO_COVER', label: 'Buy To Cover' },
];

const PREVIEW_DEBOUNCE_MS = 450;

function intentLabel(intent: TransactionIntent): string {
  switch (intent) {
    case 'BUY':
      return 'Buy';
    case 'SELL':
      return 'Sell';
    case 'SELL_SHORT':
      return 'Sell Short';
    case 'BUY_TO_COVER':
      return 'Buy To Cover';
  }
}

function localDateTimeValue(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  const local = new Date(now.getTime() - offset * 60_000);
  return local.toISOString().slice(0, 16);
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function priceDigits(value: number | null | undefined): number {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 2;
  }
  if (value >= 1000) {
    return 2;
  }
  return value >= 1 ? 4 : 8;
}

function MetricRow({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string;
  tone?: 'positive' | 'negative' | 'muted' | 'strong';
  hint?: string;
}) {
  const tones = {
    positive: 'text-terminal-green',
    negative: 'text-terminal-red',
    muted: 'text-terminal-muted',
    strong: 'text-terminal-text',
  } as const;
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-2xs text-terminal-muted">{label}</span>
      <span className="min-w-0 text-right">
        <span className={cn('num text-xs font-medium', tones[tone ?? 'strong'])}>{value}</span>
        {hint ? <span className="ml-1 text-2xs text-terminal-muted">{hint}</span> : null}
      </span>
    </div>
  );
}

function PriceCard({
  quote,
  historical,
  loading,
  fallbackError,
}: {
  quote: Quote | null;
  historical: boolean;
  loading: boolean;
  fallbackError?: string | null;
}) {
  const price = quote?.price ?? null;
  const currency = quote?.currency ?? '';
  const unavailable = !quote || price === null;
  return (
    <div className="rounded-sm border border-terminal-border bg-terminal-panelAlt px-2.5 py-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-2xs font-medium text-terminal-muted">
          {historical ? 'Historical Reference Price' : 'Current Market Price'}
        </p>
        <Badge tone={quoteTone(quote)} dot title={quote?.provider ?? 'No quote'}>
          {quoteLabel(quote)}
        </Badge>
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-0.5" aria-live="polite">
        {unavailable ? (
          <span className="text-sm font-semibold text-terminal-muted">
            {loading ? 'Loading Quote…' : 'Unavailable'}
          </span>
        ) : (
          <>
            <span className="num text-lg font-semibold text-terminal-text">
              {formatNumber(price, priceDigits(price))}
            </span>
            <span className="text-2xs text-terminal-muted">{currency}</span>
          </>
        )}
      </div>
      <div className="mt-1 space-y-0.5 text-2xs text-terminal-muted">
        {quote ? (
          <>
            <p className="truncate">
              {quote.provider}
              {quote.quote_time ? ` · Quote ${formatDateTime(quote.quote_time)}` : ''}
              {quote.age_seconds !== null && quote.age_seconds !== undefined
                ? ` · ${formatAge(quote.age_seconds)}`
                : ''}
            </p>
            {quote.market_status ? <p>{quote.market_status}</p> : null}
          </>
        ) : (
          <p>
            {fallbackError ??
              'A usable quote is required before a transaction can be recorded.'}
          </p>
        )}
        {unavailable && quote?.error ? <p className="text-terminal-amber">{quote.error}</p> : null}
      </div>
    </div>
  );
}

export function TransactionForm({
  positions,
  onRecorded,
  closeRequest,
}: {
  positions: Position[];
  onRecorded: (response: AddTransactionResponse, message: string) => void;
  closeRequest?: { position: Position; requestId: number } | null;
}) {
  const [side, setSide] = useState<TransactionIntent>('BUY');
  const [amount, setAmount] = useState('');
  const [tradeTime, setTradeTime] = useState(localDateTimeValue);
  const [fees, setFees] = useState('0');
  const [notes, setNotes] = useState('');
  const [resolution, setResolution] = useState<Instrument | null>(null);
  const [preview, setPreview] = useState<TransactionPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(newIdempotencyKey);
  const formContainerRef = useRef<HTMLDivElement>(null);
  const appliedCloseRequestId = useRef<number | null>(null);

  const parsedAmount = Number(amount);
  const parsedFees = Number(fees || '0');
  const tradeDate = new Date(tradeTime);
  const tradeTimeValid = !Number.isNaN(tradeDate.getTime());
  const canonicalTradeTime = tradeTimeValid ? tradeDate.toISOString() : null;
  const instrumentId = resolution?.instrument_id ?? null;
  const currency = resolution?.currency ?? '';
  const amountValid = Number.isFinite(parsedAmount) && parsedAmount > 0;
  const feesValid = Number.isFinite(parsedFees) && parsedFees >= 0;
  const historical = canonicalTradeTime ? isHistoricalEntry(canonicalTradeTime) : false;

  const quoteRefs = useMemo(
    () => (resolution ? [instrumentQuoteRef(resolution)] : []),
    [resolution],
  );
  const { quotes } = useQuotes(quoteRefs);
  const hubQuote = resolution ? quotes.get(resolution.instrument_id) ?? null : null;

  // A new market tick changes the derived quantity, so the preview refreshes
  // when the selected instrument's live quote moves. Backdated entries ignore
  // live ticks because their reference price comes from provider history.
  const livePriceSignal = historical
    ? ''
    : `${hubQuote?.price ?? ''}:${hubQuote?.quote_time ?? ''}`;

  // Editing the transaction intent clears the previous estimate immediately;
  // quote-driven refreshes keep the last estimate visible while recalculating.
  const intentSignature = [
    instrumentId,
    side,
    parsedAmount,
    canonicalTradeTime,
    parsedFees,
    currency,
    amountValid,
    feesValid,
  ].join('|');
  useEffect(() => {
    setPreview(null);
  }, [intentSignature]);

  useEffect(() => {
    if (!closeRequest) return;
    const { position } = closeRequest;
    const isShort = position.position_side === 'SHORT' || position.quantity < 0;
    const referencePrice = position.current_price ?? position.average_cost;
    setResolution({
      instrument_id: position.instrument_id,
      symbol: position.symbol,
      name: position.name,
      market: position.market,
      exchange: position.exchange,
      currency: position.currency,
      asset_type: position.asset_type,
      provider: position.provider,
      provider_symbol: position.provider_symbol,
    });
    setSide(isShort ? 'BUY_TO_COVER' : 'SELL');
    setAmount(String(Math.abs(position.quantity) * referencePrice));
    setError(null);
    setPreview(null);
    formContainerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [closeRequest]);

  // Server-authoritative amount-to-quantity preview. React renders this result
  // and never calculates the accounting quantity itself.
  useEffect(() => {
    if (!instrumentId || !currency || !canonicalTradeTime || !amountValid || !feesValid) {
      setPreviewLoading(false);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setPreviewLoading(true);
    const timer = window.setTimeout(() => {
      portfolioService
        .previewTransaction(
          {
            instrument_id: instrumentId,
            intent: side,
            amount: parsedAmount,
            currency,
            fees: parsedFees,
            trade_time: canonicalTradeTime,
            notes: null,
          },
          controller.signal,
        )
        .then((response) => {
          if (active) {
            setPreview(response);
          }
        })
        .catch((caught: unknown) => {
          if (!active || isAbort(caught)) {
            return;
          }
          setPreview({ valid: false, error: messageOf(caught) });
        })
        .finally(() => {
          if (active) {
            setPreviewLoading(false);
          }
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [instrumentId, side, parsedAmount, canonicalTradeTime, parsedFees, currency, amountValid, feesValid, livePriceSignal]);

  // A changed intent is a new transaction; an unchanged retry keeps its key so
  // repeated submissions cannot duplicate the ledger row.
  useEffect(() => {
    setIdempotencyKey(newIdempotencyKey());
  }, [instrumentId, side, parsedAmount, canonicalTradeTime]);

  async function recordTrade(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!resolution) {
      setError('Select a supported instrument before recording a trade');
      return;
    }
    if (!amountValid) {
      setError('Enter a positive amount');
      return;
    }
    if (!feesValid) {
      setError('Fees must be zero or positive');
      return;
    }
    if (!canonicalTradeTime) {
      setError('Enter a valid transaction time');
      return;
    }
    if (!preview?.valid) {
      setError(preview?.error ?? 'A usable quote is required before recording');
      return;
    }

    setSaving(true);
    try {
      const instrument = resolution;
      const saved = await portfolioService.addTransaction({
        instrument_id: instrument.instrument_id,
        intent: side,
        amount: parsedAmount,
        currency: instrument.currency,
        fees: parsedFees,
        trade_time: canonicalTradeTime,
        notes: notes.trim() || null,
        idempotency_key: idempotencyKey,
      });

      const unit = assetUnit(instrument.symbol, instrument.market, instrument.currency);
      const transaction = saved.transaction;
      const savedIntent = transaction.intent ?? transaction.side;
      const sideLabel = intentLabel(savedIntent);
      const message = saved.duplicate
        ? `${sideLabel} ${instrument.symbol} was already recorded; the existing ledger row was returned.`
        : `${sideLabel} ${instrument.symbol} recorded · ${formatNumber(
            transaction.quantity,
            8,
          )} ${unit} at ${formatNumber(transaction.price, priceDigits(transaction.price))} ${
            instrument.currency
          }`;

      setAmount('');
      setFees('0');
      setNotes('');
      setIdempotencyKey(newIdempotencyKey());
      onRecorded(saved, message);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setSaving(false);
    }
  }

  const unit = assetUnit(resolution?.symbol, resolution?.market, resolution?.currency);
  const previewQuote = preview?.valid ? preview.quote ?? null : null;
  // A backdated entry must never display (or imply) the current market price.
  const referenceQuote = historical ? previewQuote : hubQuote ?? previewQuote;
  const referenceLoading = historical ? previewLoading : previewLoading;
  const canSubmit = Boolean(resolution) && preview?.valid === true && !saving;
  // Show the owner's recorded holdings even before an amount is entered; the
  // preview substitutes its server-computed availability once it is ready.
  const heldQuantity =
    resolution === null
      ? null
      : (() => {
          const position = positions.find(
            (item) => item.instrument_id === resolution.instrument_id,
          );
          return position ? Math.abs(position.quantity) : null;
        })();
  const availableQuantity =
    preview?.valid && preview.available_quantity !== null && preview.available_quantity !== undefined
      ? preview.available_quantity
      : heldQuantity;
  const maxSellAmount = preview?.valid
    ? side === 'BUY_TO_COVER'
      ? preview.max_close_amount ?? preview.max_sell_amount ?? null
      : preview.max_sell_amount ?? null
    : null;

  useEffect(() => {
    if (
      !closeRequest ||
      !preview?.valid ||
      maxSellAmount === null ||
      maxSellAmount <= 0 ||
      appliedCloseRequestId.current === closeRequest.requestId ||
      resolution?.instrument_id !== closeRequest.position.instrument_id
    ) return;
    const isShort = closeRequest.position.position_side === 'SHORT' || closeRequest.position.quantity < 0;
    const closeIntent = isShort ? 'BUY_TO_COVER' : 'SELL';
    if (side !== closeIntent) return;
    appliedCloseRequestId.current = closeRequest.requestId;
    setAmount(String(maxSellAmount));
  }, [closeRequest, maxSellAmount, preview?.valid, resolution?.instrument_id, side]);

  return (
    <div ref={formContainerRef} className="xl:col-span-4">
    <Card title="Record Transaction" subtitle="Manual Exposure Ledger · No Execution">
      <form onSubmit={recordTrade} className="space-y-2.5">
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className="mb-1 block text-2xs font-medium text-terminal-muted">Instrument</label>
            <InstrumentSearch
              value={resolution?.symbol ?? ''}
              onSelect={(instrument) => {
                setResolution(instrument);
                setError(null);
              }}
              placeholder={resolution?.market === 'crypto' ? 'BTCUSDT' : resolution?.market === 'global' ? 'AAPL' : 'RELIANCE'}
              className="w-full"
              inputClassName="h-9"
            />
          </div>
          <Input
            label="Market"
            value={resolution?.market ?? ''}
            readOnly
            placeholder="Select instrument"
          />
          <Input
            label="Exchange"
            value={resolution?.exchange ?? ''}
            readOnly
            placeholder="Select instrument"
          />
          <Select
            label="Transaction Intent"
            value={side}
            onChange={(event) => {
              setSide(event.target.value as TransactionIntent);
              setError(null);
            }}
            options={sideOptions}
          />
          <Input
            label="Currency"
            value={currency}
            readOnly
            hint="Resolved From Instrument"
            placeholder="Select instrument"
          />
          <Input
            label="Fees"
            type="number"
            min={0}
            step="any"
            value={fees}
            onChange={(event) => setFees(event.target.value)}
            hint={currency ? `Charged In ${currency}` : 'Choose instrument'}
          />
        </div>

        <div
          className={cn(
            'rounded-sm border bg-black px-3 py-2 transition-colors',
            preview && !preview.valid ? 'border-[#3f2528]' : 'border-terminal-border',
          )}
        >
          <Field
            label={`${
              side === 'BUY'
                ? 'Amount To Invest'
                : side === 'SELL'
                  ? 'Amount To Sell'
                  : side === 'SELL_SHORT'
                    ? 'Short Exposure Notional'
                    : 'Cover Notional'
            } (${currency})`}
            hint={
              preview && !preview.valid
                ? undefined
                : 'Gross Asset Notional · Fees Are Separate'
            }
            error={preview && !preview.valid && amount.trim() !== '' ? preview.error : null}
          >
            <div className="flex items-baseline gap-2">
              <input
                inputMode="decimal"
                autoComplete="off"
                aria-label={`${
                  side === 'BUY'
                    ? 'Amount To Invest'
                    : side === 'SELL'
                      ? 'Amount To Sell'
                      : side === 'SELL_SHORT'
                        ? 'Short Exposure Notional'
                        : 'Cover Notional'
                } in ${currency}`}
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                placeholder="0.00"
                className="num w-full min-w-0 bg-transparent text-2xl font-semibold text-terminal-text placeholder:text-terminal-muted/50 focus:outline-none"
              />
              <span className="text-xs font-medium text-terminal-muted">{currency}</span>
              {side === 'SELL' || side === 'BUY_TO_COVER' ? (
                <button
                  type="button"
                  disabled={maxSellAmount === null || !preview?.valid}
                  onClick={() => { if (maxSellAmount !== null) setAmount(String(maxSellAmount)); }}
                  className="shrink-0 rounded-full border border-terminal-border px-2 py-1 text-2xs font-medium text-terminal-accent hover:border-terminal-accent disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label={`Use maximum ${side === 'SELL' ? 'sell' : 'cover'} amount`}
                  title="Use the server-calculated maximum close amount"
                >
                  Max
                </button>
              ) : null}
            </div>
          </Field>
        </div>

        <PriceCard
          quote={referenceQuote}
          historical={historical}
          loading={referenceLoading}
          fallbackError={preview?.valid ? null : preview?.error ?? null}
        />

        <div className="space-y-1 rounded-sm border border-terminal-borderSoft px-2.5 py-2">
          <MetricRow
            label="Estimated Quantity"
            value={
              preview?.valid && preview.quantity !== undefined
                ? formatNumber(preview.quantity, 8)
                : previewLoading
                  ? 'Calculating…'
                  : '—'
            }
            tone={preview?.valid ? 'strong' : 'muted'}
            hint={preview?.valid ? unit : undefined}
          />
          <MetricRow
            label={side === 'BUY' || side === 'BUY_TO_COVER' ? 'Calculated Notional' : 'Reference Notional'}
            value={
              preview?.valid && preview.actual_amount !== undefined
                ? formatNumber(preview.actual_amount, 2)
                : '—'
            }
            tone="muted"
            hint={preview?.valid ? currency : undefined}
          />
          {preview?.valid && (preview.remaining_amount ?? 0) > 0 ? (
            <MetricRow
              label="Remaining Amount"
              value={formatNumber(preview.remaining_amount, 2)}
              tone="muted"
              hint={`${currency} · Not Spent`}
            />
          ) : null}
          {side === 'BUY' ? (
            <MetricRow
              label="Total Cash Cost"
              value={
                preview?.valid && preview.total_cash_cost !== null && preview.total_cash_cost !== undefined
                  ? formatNumber(preview.total_cash_cost, 2)
                  : '—'
              }
              tone="muted"
              hint={preview?.valid ? currency : undefined}
            />
          ) : side === 'SELL' ? (
            <MetricRow
              label="Net Sale Proceeds"
              value={
                preview?.valid && preview.net_proceeds !== null && preview.net_proceeds !== undefined
                  ? formatNumber(preview.net_proceeds, 2)
                  : '—'
              }
              tone="muted"
              hint={preview?.valid ? currency : undefined}
            />
          ) : (
            <MetricRow
              label="Manual Exposure Reference"
              value={
                preview?.valid && preview.actual_amount !== undefined
                  ? formatNumber(preview.actual_amount, 2)
                  : '—'
              }
              tone="muted"
              hint={preview?.valid ? `${currency} · Not An Execution` : undefined}
            />
          )}
          {side === 'SELL' || side === 'BUY_TO_COVER' ? (
            <>
              <MetricRow
                label={side === 'SELL' ? 'Available Long Holdings' : 'Available Short Exposure'}
                value={
                  availableQuantity !== null && availableQuantity !== undefined
                    ? formatNumber(availableQuantity, 8)
                    : '—'
                }
                tone="muted"
                hint={availableQuantity !== null && availableQuantity !== undefined ? unit : undefined}
              />
              <MetricRow
                label={side === 'SELL' ? 'Max Sellable Notional' : 'Max Cover Notional'}
                value={maxSellAmount !== null ? formatNumber(maxSellAmount, 2) : '—'}
                tone="muted"
                hint={maxSellAmount !== null ? currency : undefined}
              />
            </>
          ) : null}
          {preview?.valid && preview.trading_rules ? (
            <p className="pt-0.5 text-2xs text-terminal-muted">
              Quantity Rules: {preview.trading_rules.source}
            </p>
          ) : null}
        </div>

        {historical ? (
          <Notice tone="warning">
            Historical Entry · The reference price is the provider price at or before the selected
            transaction time. The current market price is never substituted.
          </Notice>
        ) : null}

        {preview?.valid && preview.warnings?.length ? (
          <Notice tone="warning">{preview.warnings.join(' ')}</Notice>
        ) : null}

        <Input
          label="Transaction Time"
          type="datetime-local"
          value={tradeTime}
          onChange={(event) => setTradeTime(event.target.value)}
          error={tradeTimeValid ? null : 'Enter a valid transaction time'}
        />

        <Textarea
          label="Notes (Optional)"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Broker reference, charges, partial fill"
        />

        {error ? <Notice tone="negative">{error}</Notice> : null}

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="submit"
            variant="primary"
            icon="plus"
            loading={saving}
            disabled={!canSubmit}
          >
            Record {intentLabel(side)}
          </Button>
          <span className="text-2xs text-terminal-muted">
            FIFO · Fees Included · No Order Execution
          </span>
        </div>
        <p className="text-2xs leading-relaxed text-terminal-muted">
          Reference Quantity Uses A Verified Provider Quote. No Exchange Order Is Placed.
        </p>
      </form>
    </Card>
    </div>
  );
}
