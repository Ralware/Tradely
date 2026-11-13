import type { IndicatorValues } from '../../types/api';
import { clamp, cn, formatCompact, formatNumber } from '../../utils/format';
import { Card } from '../common/Card';

type Tone = 'accent' | 'positive' | 'negative' | 'warning' | 'violet';

const toneText: Record<Tone, string> = {
  accent: 'text-terminal-accent',
  positive: 'text-terminal-green',
  negative: 'text-terminal-red',
  warning: 'text-terminal-amber',
  violet: 'text-terminal-violet',
};

const toneBar: Record<Tone, string> = {
  accent: 'bg-terminal-accent',
  positive: 'bg-terminal-green',
  negative: 'bg-terminal-red',
  warning: 'bg-terminal-amber',
  violet: 'bg-terminal-violet',
};

function valueOf(indicators: IndicatorValues, field: string): number | null {
  const value = indicators[field];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function Meter({
  label,
  value,
  fraction,
  tone = 'accent',
  hint,
}: {
  label: string;
  value: string;
  fraction: number;
  tone?: Tone;
  hint?: string;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[11px] text-terminal-muted">{label}</span>
        <span className={cn('num text-xs font-medium', toneText[tone])}>{value}</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-terminal-borderSoft">
        <div
          className={cn('h-full rounded-full transition-[width]', toneBar[tone])}
          style={{ width: `${clamp(fraction, 0, 1) * 100}%` }}
        />
      </div>
      {hint ? <p className="mt-0.5 text-[10px] text-terminal-muted">{hint}</p> : null}
    </div>
  );
}

export function IndicatorPanel({
  indicators,
  close,
  className,
}: {
  indicators: IndicatorValues;
  close: number | null;
  className?: string;
}) {
  const rsi = valueOf(indicators, 'rsi_14');
  const stochRsi = valueOf(indicators, 'stoch_rsi_14');
  const adx = valueOf(indicators, 'adx');
  const plusDi = valueOf(indicators, 'plus_di');
  const minusDi = valueOf(indicators, 'minus_di');
  const macd = valueOf(indicators, 'macd');
  const macdSignal = valueOf(indicators, 'macd_signal');
  const macdHist = valueOf(indicators, 'macd_hist');
  const atr = valueOf(indicators, 'atr_14');
  const rvol = valueOf(indicators, 'rvol_20');
  const mfi = valueOf(indicators, 'mfi_14');
  const cmf = valueOf(indicators, 'cmf_20');
  const cci = valueOf(indicators, 'cci_20');
  const obv = valueOf(indicators, 'obv');
  const vwap = valueOf(indicators, 'vwap_session');
  const bbUpper = valueOf(indicators, 'bb_upper');
  const bbLower = valueOf(indicators, 'bb_lower');

  const bandPosition =
    close !== null && bbUpper !== null && bbLower !== null && bbUpper > bbLower
      ? (close - bbLower) / (bbUpper - bbLower)
      : null;

  return (
    <Card
      title="Indicator values"
      subtitle="Latest completed bar, calculated by the FastAPI backend."
      className={className}
    >
      <div className="space-y-4">
        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-terminal-muted">
            Momentum
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Meter
              label="RSI 14"
              value={rsi === null ? '—' : formatNumber(rsi, 1)}
              fraction={(rsi ?? 0) / 100}
              tone={rsi === null ? 'accent' : rsi >= 70 || rsi <= 30 ? 'warning' : 'accent'}
              hint="30 / 70 context levels"
            />
            <Meter
              label="Stochastic RSI 14"
              value={stochRsi === null ? '—' : formatNumber(stochRsi, 1)}
              fraction={(stochRsi ?? 0) / 100}
              tone={stochRsi === null ? 'accent' : stochRsi >= 80 || stochRsi <= 20 ? 'warning' : 'violet'}
            />
            <Meter
              label="MACD"
              value={macd === null ? '—' : formatNumber(macd, 3)}
              fraction={macdHist === null ? 0.5 : clamp(0.5 + macdHist / 20, 0, 1)}
              tone={macdHist === null ? 'accent' : macdHist >= 0 ? 'positive' : 'negative'}
              hint={`Signal ${macdSignal === null ? '—' : formatNumber(macdSignal, 3)} · Hist ${
                macdHist === null ? '—' : formatNumber(macdHist, 3)
              }`}
            />
            <Meter
              label="CCI 20"
              value={cci === null ? '—' : formatNumber(cci, 1)}
              fraction={cci === null ? 0.5 : (cci + 200) / 400}
              tone={cci === null ? 'accent' : cci >= 100 ? 'warning' : cci <= -100 ? 'negative' : 'accent'}
            />
          </div>
        </div>

        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-terminal-muted">
            Trend strength
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Meter
              label="ADX 14"
              value={adx === null ? '—' : formatNumber(adx, 1)}
              fraction={(adx ?? 0) / 60}
              tone={adx === null ? 'accent' : adx >= 20 ? 'positive' : 'accent'}
              hint="≥ 20 indicates a trending regime"
            />
            <Meter
              label="Directional index (+DI / −DI)"
              value={
                plusDi === null && minusDi === null
                  ? '—'
                  : `${plusDi === null ? '—' : formatNumber(plusDi, 1)} / ${
                      minusDi === null ? '—' : formatNumber(minusDi, 1)
                    }`
              }
              fraction={plusDi === null ? 0.5 : plusDi / 60}
              tone={
                plusDi === null || minusDi === null
                  ? 'accent'
                  : plusDi > minusDi
                    ? 'positive'
                    : 'negative'
              }
              hint="ADX shows strength, not direction"
            />
          </div>
        </div>

        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-terminal-muted">
            Volatility
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Meter
              label="ATR 14"
              value={atr === null ? '—' : formatNumber(atr, 2)}
              fraction={atr !== null && close ? clamp(atr / close / 0.1, 0, 1) : 0}
              tone="violet"
              hint={close && atr !== null ? `${formatNumber((atr / close) * 100, 2)}% of close` : undefined}
            />
            <Meter
              label="Bollinger position"
              value={bandPosition === null ? '—' : `${formatNumber(bandPosition * 100, 1)}%`}
              fraction={bandPosition ?? 0.5}
              tone={
                bandPosition === null
                  ? 'accent'
                  : bandPosition > 0.8 || bandPosition < 0.2
                    ? 'warning'
                    : 'accent'
              }
              hint={
                bbLower !== null && bbUpper !== null
                  ? `Lower ${formatNumber(bbLower, 2)} · Upper ${formatNumber(bbUpper, 2)}`
                  : undefined
              }
            />
          </div>
        </div>

        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-terminal-muted">
            Volume
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Meter
              label="Relative volume 20"
              value={rvol === null ? '—' : formatNumber(rvol, 2)}
              fraction={(rvol ?? 0) / 3}
              tone={rvol === null ? 'accent' : rvol >= 1 ? 'positive' : 'accent'}
              hint="≥ 1.0 = above the prior 20-bar average"
            />
            <Meter
              label="MFI 14"
              value={mfi === null ? '—' : formatNumber(mfi, 1)}
              fraction={(mfi ?? 0) / 100}
              tone={mfi === null ? 'accent' : mfi >= 80 || mfi <= 20 ? 'warning' : 'accent'}
            />
            <Meter
              label="CMF 20"
              value={cmf === null ? '—' : formatNumber(cmf, 3)}
              fraction={cmf === null ? 0.5 : (cmf + 1) / 2}
              tone={cmf === null ? 'accent' : cmf >= 0 ? 'positive' : 'negative'}
            />
            <Meter
              label="OBV"
              value={obv === null ? '—' : formatCompact(obv)}
              fraction={0.5}
              tone="accent"
              hint="Cumulative volume; compare direction, not absolute level"
            />
          </div>
        </div>

        <div className="rounded-lg border border-terminal-borderSoft bg-terminal-panelAlt px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-terminal-muted">
            Session VWAP
          </p>
          <p className="num mt-0.5 text-xs text-terminal-text">
            {vwap === null ? 'Unavailable on daily bars' : formatNumber(vwap, 2)}
          </p>
          {vwap === null ? (
            <p className="mt-0.5 text-[10px] text-terminal-muted">
              Daily OHLCV cannot reconstruct the intraday volume distribution.
            </p>
          ) : null}
        </div>
      </div>
    </Card>
  );
}
