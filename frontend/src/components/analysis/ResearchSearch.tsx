import { useEffect, useState } from 'react';
import { API_BASE_URL, apiRequest } from '../../services/api';
import { Card } from '../common/Card';
import { Input, Select } from '../common/Field';
import { Button } from '../common/Button';

const url = '/api/backtests/research';
const columns = [
  ['config_id', 'Configuration'], ['trades', 'Trades'], ['gross_pnl', 'Gross P/L'],
  ['total_maker_fees', 'Maker fees'], ['total_taker_fees', 'Taker fees'], ['total_fees', 'Total fees'],
  ['total_funding', 'Funding'], ['net_pnl', 'Net P/L'], ['net_return_pct', 'Net return %'],
  ['net_profit_factor', 'Net PF'], ['max_drawdown_pct', 'Drawdown %'],
];
type Run = { status: string; mode: string; timeframe: string; completed: number; total: number; rate: number; backend: string | null;
  fallback: string | null; error: string | null; top: Record<string, string>[]; cancel_requested: boolean };
const active = (run: Run | null) => !run || ['starting', 'running'].includes(run.status);

export function ResearchSearch() {
  const [mode, setMode] = useState('auto');
  const [timeframe, setTimeframe] = useState('2h');
  const [count, setCount] = useState('20');
  const [id, setId] = useState(() => localStorage.getItem('tradely.research.run'));
  const [refresh, setRefresh] = useState(0);
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [hardware, setHardware] = useState<{cpu: string; cuda_device: string | null; adapters: string[]} | null>(null);
  useEffect(() => {
    apiRequest<typeof hardware>(url + '/hardware').then(setHardware).catch(e => setError(String(e)));
  }, []);
  useEffect(() => {
    if (!id) return;
    let closed = false;
    let timer: number;
    async function poll() {
      try {
        const value = await apiRequest<Run>(url + '/' + id);
        if (closed) return;
        setRun(value);
        setError('');
        if (active(value)) timer = window.setTimeout(poll, 1000);
      } catch (e) {
        if (!closed) {
          setError(String(e));
          timer = window.setTimeout(poll, 3000);
        }
      }
    }
    void poll();
    return () => { closed = true; window.clearTimeout(timer); };
  }, [id, refresh]);
  async function launch() {
    setBusy(true);
    try {
      const job = await apiRequest<{id: string}>(url, {method: 'POST', body: {mode, timeframe, combinations: Number(count)}});
      localStorage.setItem('tradely.research.run', job.id);
      setRun(null);
      setId(job.id);
      setError('');
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  const running = !!id && active(run);
  return <Card className="mb-3" title="EMA Pullback parameter search" subtitle="BTCUSDT perpetual · Binance USD-M · January 2024 through December 2025">
    <p className="mb-2 text-xs text-terminal-muted">1,000 USDT starting equity · Maker 0.05% · Taker 0.02% · Zero slippage · Historical funding</p>
    <div className="grid gap-2 sm:grid-cols-3">
      <Select label="Execution mode" value={mode} onChange={e => setMode(e.target.value)} options={[{value:'auto',label:'Automatic'},{value:'cpu',label:'CPU'},{value:'gpu',label:'GPU with CPU fallback'}]} />
      <Select label="Timeframe" value={timeframe} onChange={e => setTimeframe(e.target.value)} options={['2h','4h','1d'].map(value => ({value,label:value}))} />
      <Input label="Configurations" type="number" min={1} max={45000} value={count} onChange={e => setCount(e.target.value)} />
    </div>
    <div className="my-2 flex flex-wrap items-center gap-2">
      <Button disabled={busy || (running && !error) || !Number.isInteger(+count) || +count < 1 || +count > 45000} onClick={launch}>Run search</Button>
      {running && <Button disabled={run?.cancel_requested} onClick={async () => {
        try { await apiRequest(url + '/' + id, {method:'DELETE'}); } catch (e) { setError(String(e)); }
      }}>{run?.cancel_requested ? 'Finishing submitted batches' : 'Cancel'}</Button>}
      {run && ['interrupted','failed'].includes(run.status) && <Button disabled={busy} onClick={async () => {
        setBusy(true);
        try {
          await apiRequest(url + '/' + id + '/resume', {method:'POST'});
          setRun(null);
          setRefresh(value => value + 1);
        } catch (e) { setError(String(e)); } finally { setBusy(false); }
      }}>Resume search</Button>}
      {hardware && <span className="text-xs">{hardware.cpu} · {[...hardware.adapters, hardware.cuda_device ? 'CUDA available' : 'CUDA unavailable'].join(' ? ')}</span>}
    </div>
    {error && <p role="alert">{error}</p>}
    {run && <div className="text-xs" aria-live="polite">
      {run.timeframe} / {run.mode} / {run.status} · {run.completed}/{run.total} configurations · {run.rate.toFixed(2)}/s
      {run.backend && ' · ' + run.backend.toUpperCase()}
      {running && run.rate > 0 && ' · ETA ' + Math.ceil((run.total-run.completed)/run.rate) + ' s'}
      {run.fallback && <p>CPU fallback · {run.fallback}</p>}
      {run.error && <p role="alert">{run.error}</p>}
      {!running && run.completed > 0 && <a className="ml-2 underline" href={API_BASE_URL + url + '/' + id + '/csv'}>Download all results</a>}
      {run.top.length > 0 && <div className="mt-2 overflow-x-auto"><table><thead><tr>{columns.map(([k,label]) => <th className="px-2" key={k}>{label}</th>)}</tr></thead>
        <tbody>{run.top.map(row => <tr key={row.config_id}>{columns.map(([k]) => <td className="p-1 text-right normal-case" key={k}>{k === 'config_id' || !row[k] || !Number.isFinite(Number(row[k])) ? row[k] || '—' : Number(row[k]).toLocaleString(undefined,{maximumFractionDigits:4})}</td>)}</tr>)}</tbody></table></div>}
      {!running && run.completed > 0 && !run.top.length && <p>No configurations met the minimum trade count for ranking.</p>}
    </div>}
  </Card>;
}
