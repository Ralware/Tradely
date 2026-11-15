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
  label: `${limit} Records`,
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
    <div className="w-full px-4 py-4 lg:px-6">
      <PageHeader
        title="Settings"
        subtitle="Runtime · Providers · Signal Audits"
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

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
        <Card className="xl:col-span-6" title="Application Status">
          {healthLoading && !health ? (
            <LoadingPanel label="Checking Backend" rows={4} />
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
                label="AI Decision Engine"
                value={<Badge tone={health.ai ? 'negative' : 'positive'}>{health.ai ? 'Enabled' : 'Disabled'}</Badge>}
              />
              <KeyValue
                label="Paper Trading"
                value={<Badge tone={health.paper_trading ? 'negative' : 'positive'}>{health.paper_trading ? 'Enabled' : 'Disabled'}</Badge>}
              />
              <KeyValue
                label="Order Execution"
                value={<Badge tone={health.order_execution ? 'negative' : 'positive'}>{health.order_execution ? 'Enabled' : 'Disabled'}</Badge>}
              />
              <KeyValue label="Server Time" value={formatDateTime(health.timestamp)} />
            </dl>
          ) : null}
        </Card>

        <Card className="xl:col-span-6" title="Data Providers">
          {providersLoading && !providers ? (
            <LoadingPanel label="Checking Providers" rows={4} />
          ) : providersError ? (
            <ErrorState message={providersError} onRetry={refresh} />
          ) : providers ? (
            <>
              <ProviderList providers={providers.providers} />
              <p className="mt-2 text-2xs text-terminal-muted">
                Checked {formatDateTime(providers.checked_at)} · Keys Stay in Backend `.env`
              </p>
            </>
          ) : null}
        </Card>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-12">
        <Card className="xl:col-span-5" title="Frontend Configuration">
          <dl className="divide-y divide-terminal-borderSoft">
            <KeyValue label="VITE_API_BASE_URL" value={API_BASE_URL || 'Same-Origin Proxy'} />
            <KeyValue label="Backend Origin" value={backendOrigin} />
            <KeyValue label="Vite Dev Server" value="http://localhost:5173" />
            <KeyValue label="FastAPI" value="http://127.0.0.1:8000" />
            <KeyValue label="Proxy Prefix" value="/api → FastAPI" />
            <KeyValue label="Static Build" value="frontend/dist" />
          </dl>
        </Card>

        <Card className="xl:col-span-7" title="API Documentation">
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
          <Notice tone="warning" className="mt-2">
            This build adds read-only `GET /api/instruments/&#123;symbol&#125;/indicators` and
            `GET /api/instruments/&#123;symbol&#125;/technicals`. Existing routes and formulas are
            unchanged.
          </Notice>
        </Card>
      </div>

      <Card
        className="mt-3"
        title="Signal Audit History"
        actions={
          <Select
            value={limit}
            onChange={(event) => setLimit(event.target.value)}
            options={limitOptions}
            wrapperClassName="w-32"
          />
        }
      >
        {signals.loading && !signals.data ? (
          <LoadingPanel label="Loading Signals" rows={5} />
        ) : signals.error ? (
          <ErrorState message={signals.error} onRetry={signals.reload} />
        ) : (signals.data?.signals.length ?? 0) === 0 ? (
          <EmptyState title="No Signal Audits" description="Open an analysis page." icon="chart" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-xs">
              <thead>
                <tr className="border-b border-terminal-border text-left text-2xs text-terminal-muted">
                  <th className="py-1.5 pr-3 font-medium">Symbol</th>
                  <th className="py-1.5 pr-3 font-medium">Market</th>
                  <th className="py-1.5 pr-3 font-medium">State</th>
                  <th className="py-1.5 pr-3 font-medium">Strategy</th>
                  <th className="py-1.5 pr-3 font-medium">As Of</th>
                  <th className="py-1.5 font-medium">Source</th>
                </tr>
              </thead>
              <tbody>
                {(signals.data?.signals ?? []).map((signal, index) => (
                  <tr
                    key={`${signal.symbol}-${signal.as_of ?? index}-${index}`}
                    className="border-b border-terminal-borderSoft last:border-0"
                  >
                    <td className="py-1.5 pr-3 font-medium text-terminal-text">{signal.symbol}</td>
                    <td className="py-1.5 pr-3 text-terminal-muted">{signal.market}</td>
                    <td className="py-1.5 pr-3">
                      <SignalBadge state={signal.state} />
                    </td>
                    <td className="py-1.5 pr-3 text-terminal-muted">
                      {signal.strategy} · {signal.strategy_version}
                    </td>
                    <td className="num py-1.5 pr-3 text-terminal-muted">{formatDateTime(signal.as_of)}</td>
                    <td className="py-1.5 text-terminal-muted">{signal.data_source ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Notice className="mt-3">Local Research Tool · Do Not Expose FastAPI to Untrusted Networks</Notice>
    </div>
  );
}
