import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { useApiStatus } from '../contexts/ApiStatusContext';
import { analysisService } from '../services/analysisService';
import { API_BASE_URL } from '../services/api';
import { formatDateTime } from '../utils/format';
import { Badge } from '../components/common/Badge';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { Select } from '../components/common/Field';
import { PageHeader } from '../components/common/PageHeader';
import { EmptyState, ErrorState, LoadingPanel, Notice } from '../components/common/States';
import { KeyValue } from '../components/common/Stat';
import { ProviderList } from '../components/tables/ProviderList';
import { SignalBadge } from '../components/signals/SignalBadge';

const backendOrigin = API_BASE_URL || 'http://127.0.0.1:8000';

const limitOptions = [25, 50, 100, 200, 500].map((limit) => ({
  value: String(limit),
  label: `${limit} records`,
}));

export function SettingsPage() {
  const { health, healthLoading, healthError, providers, providersLoading, providersError, refresh } =
    useApiStatus();
  const [limit, setLimit] = useState('50');
  const signals = useApi(
    (signal) => analysisService.getSignalsHistory(Number(limit), signal),
    [limit],
  );

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="Runtime configuration reported by the backend, provider state and the signal audit trail. Secrets are never exposed by these endpoints."
        actions={
          <Button
            size="sm"
            icon="refresh"
            onClick={() => {
              refresh();
              signals.reload();
            }}
          >
            Refresh
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-6" title="Application status" subtitle="GET /api/health">
          {healthLoading && !health ? (
            <LoadingPanel label="Checking backend…" rows={4} />
          ) : healthError ? (
            <ErrorState message={healthError} onRetry={refresh} />
          ) : health ? (
            <dl className="divide-y divide-terminal-borderSoft">
              <KeyValue
                label="Status"
                value={<Badge tone={health.status === 'ok' ? 'positive' : 'warning'}>{health.status}</Badge>}
              />
              <KeyValue label="Application" value={health.application} />
              <KeyValue label="Mode" value={health.mode} />
              <KeyValue
                label="AI decision engine"
                value={<Badge tone={health.ai ? 'negative' : 'positive'}>{health.ai ? 'enabled' : 'disabled'}</Badge>}
              />
              <KeyValue
                label="Paper trading"
                value={<Badge tone={health.paper_trading ? 'negative' : 'positive'}>{health.paper_trading ? 'enabled' : 'disabled'}</Badge>}
              />
              <KeyValue
                label="Order execution"
                value={<Badge tone={health.order_execution ? 'negative' : 'positive'}>{health.order_execution ? 'enabled' : 'disabled'}</Badge>}
              />
              <KeyValue label="Server timestamp" value={formatDateTime(health.timestamp)} />
            </dl>
          ) : null}
        </Card>

        <Card className="xl:col-span-6" title="Data providers" subtitle="GET /api/providers/status">
          {providersLoading && !providers ? (
            <LoadingPanel label="Checking providers…" rows={4} />
          ) : providersError ? (
            <ErrorState message={providersError} onRetry={refresh} />
          ) : providers ? (
            <>
              <ProviderList providers={providers.providers} />
              <p className="mt-3 text-[10px] text-terminal-muted">
                Checked {formatDateTime(providers.checked_at)}. Configure keys and user agents in
                the backend `.env`; they are never read from the browser.
              </p>
            </>
          ) : null}
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-5" title="Frontend configuration" subtitle="Build-time environment and development ports.">
          <dl className="divide-y divide-terminal-borderSoft">
            <KeyValue label="VITE_API_BASE_URL" value={API_BASE_URL || '(empty — same-origin proxy)'} />
            <KeyValue label="Resolved backend origin" value={backendOrigin} />
            <KeyValue label="Vite dev server" value="http://localhost:5173" />
            <KeyValue label="FastAPI" value="http://127.0.0.1:8000" />
            <KeyValue label="Proxy prefix" value="/api → FastAPI" />
            <KeyValue label="Static build" value="frontend/dist" />
          </dl>
          <Notice className="mt-3">
            For a separately hosted build, set `VITE_API_BASE_URL` to the FastAPI origin and reverse
            proxy `/api`, or enable CORS on the backend. The default development setup needs neither.
          </Notice>
        </Card>

        <Card className="xl:col-span-7" title="API documentation" subtitle="Generated by FastAPI from the live route table.">
          <div className="space-y-2 text-xs">
            <p className="text-terminal-muted">
              The OpenAPI schema is the authoritative contract for the frontend. The React app never
              invents fields that are not present in the response.
            </p>
            <div className="flex flex-wrap gap-2">
              <a href={`${backendOrigin}/docs`} target="_blank" rel="noopener noreferrer">
                <Button size="sm" icon="external">
                  Swagger UI
                </Button>
              </a>
              <a href={`${backendOrigin}/openapi.json`} target="_blank" rel="noopener noreferrer">
                <Button size="sm" icon="external">
                  OpenAPI JSON
                </Button>
              </a>
            </div>
          </div>
          <Notice tone="warning" className="mt-3">
            This build adds one read-only endpoint, `GET /api/instruments/&#123;symbol&#125;/indicators`,
            which returns per-bar indicator values computed by the existing backend function. No
            existing route, formula or threshold was modified.
          </Notice>
        </Card>
      </div>

      <Card
        className="mt-4"
        title="Signal audit history"
        subtitle="GET /api/signals/history — recorded each time an analysis request is served."
        actions={
          <Select
            value={limit}
            onChange={(event) => setLimit(event.target.value)}
            options={limitOptions}
            wrapperClassName="w-36"
          />
        }
      >
        {signals.loading && !signals.data ? (
          <LoadingPanel label="Loading signal history…" rows={5} />
        ) : signals.error ? (
          <ErrorState message={signals.error} onRetry={signals.reload} />
        ) : (signals.data?.signals.length ?? 0) === 0 ? (
          <EmptyState
            title="No signal audits recorded"
            description="Open an analysis page to generate a backend signal evaluation."
            icon="chart"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-xs">
              <thead>
                <tr className="border-b border-terminal-border text-left text-[11px] uppercase tracking-[0.06em] text-terminal-muted">
                  <th className="py-2 pr-3 font-medium">Symbol</th>
                  <th className="py-2 pr-3 font-medium">Market</th>
                  <th className="py-2 pr-3 font-medium">State</th>
                  <th className="py-2 pr-3 font-medium">Strategy</th>
                  <th className="py-2 pr-3 font-medium">As of</th>
                  <th className="py-2 font-medium">Source</th>
                </tr>
              </thead>
              <tbody>
                {(signals.data?.signals ?? []).map((signal, index) => (
                  <tr
                    key={`${signal.symbol}-${signal.as_of ?? index}-${index}`}
                    className="border-b border-terminal-borderSoft last:border-0"
                  >
                    <td className="py-2 pr-3 font-medium text-terminal-text">{signal.symbol}</td>
                    <td className="py-2 pr-3 text-terminal-muted">{signal.market}</td>
                    <td className="py-2 pr-3">
                      <SignalBadge state={signal.state} />
                    </td>
                    <td className="py-2 pr-3 text-terminal-muted">
                      {signal.strategy} · {signal.strategy_version}
                    </td>
                    <td className="num py-2 pr-3 text-terminal-muted">{formatDateTime(signal.as_of)}</td>
                    <td className="py-2 text-terminal-muted">{signal.data_source ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Notice className="mt-4">
        Tradely is a local research tool. It has no authentication layer because it is intended to run
        on your machine; do not expose the FastAPI port to untrusted networks without adding access
        control.
      </Notice>
    </div>
  );
}
