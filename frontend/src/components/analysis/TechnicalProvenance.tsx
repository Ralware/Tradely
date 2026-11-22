import type { AnalyticsProvenance, TechnicalSummaryResponse } from '../../types/api';
import { formatDateTime } from '../../utils/format';

function InfoItem({ label, value, mono = false }: { label: string; value: string | number; mono?: boolean }) {
  return (
    <div className="min-w-0 border-b border-terminal-borderSoft py-1.5 last:border-0">
      <p className="text-2xs text-terminal-muted">{label}</p>
      <p className={`mt-0.5 break-all text-xs text-terminal-text ${mono ? 'font-mono' : ''}`}>{value}</p>
    </div>
  );
}

export function TechnicalProvenance({ provenance, ratings }: {
  provenance: AnalyticsProvenance;
  ratings: TechnicalSummaryResponse;
}) {
  return (
    <details className="panel-surface group">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2.5">
        <span className="text-xs font-semibold text-terminal-text">Calculation & Data Information</span>
        <span className="text-2xs text-terminal-muted group-open:hidden">Show provenance</span>
        <span className="hidden text-2xs text-terminal-muted group-open:inline">Hide provenance</span>
      </summary>
      <div className="grid grid-cols-1 gap-x-6 border-t border-terminal-border px-3 py-2 sm:grid-cols-2 xl:grid-cols-3">
        <InfoItem label="Instrument" value={`${provenance.symbol} · ${provenance.instrument_id ?? 'Unresolved ID'}`} />
        <InfoItem label="Exchange / Market" value={`${provenance.exchange ?? '—'} · ${provenance.market}`} />
        <InfoItem label="Timeframe" value={provenance.interval} />
        <InfoItem label="Candle Count" value={provenance.candle_count.toLocaleString()} />
        <InfoItem label="Latest Candle" value={formatDateTime(provenance.latest_candle_timestamp)} />
        <InfoItem label="Candle Status" value={provenance.candle_status} />
        <InfoItem label="OHLCV Fingerprint" value={provenance.ohlcv_fingerprint} mono />
        <InfoItem label="Calculation Timestamp" value={provenance.calculation_timestamp ? formatDateTime(provenance.calculation_timestamp) : 'Unavailable'} />
        <InfoItem label="Snapshot Generated" value={formatDateTime(provenance.snapshot_generated_at)} />
        <InfoItem label="Rating Source" value={ratings.source_name} />
        <InfoItem label="Source Version" value={ratings.source_version} />
        <InfoItem label="Pine Dependency" value={ratings.dependency} />
        <InfoItem label="Market Data Source" value={provenance.source} />
        <InfoItem label="Data Freshness" value={provenance.data_freshness} />
        <InfoItem label="Adjusted OHLCV" value={provenance.is_adjusted ? 'Yes' : 'No'} />
        <InfoItem label="Indicator Availability" value={`${provenance.indicator_available}/${provenance.indicator_total} · ${provenance.indicator_unavailable} unavailable`} />
        <InfoItem label="Rating Cache" value={provenance.technical_rating_cache_hit ? 'Hit' : 'Calculated'} />
      </div>
    </details>
  );
}
