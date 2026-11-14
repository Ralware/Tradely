export type Market = 'india' | 'global' | 'crypto';

export type Side = 'BUY' | 'SELL';

export type SignalState =
  | 'BUY'
  | 'SELL'
  | 'WAIT'
  | 'NO_SIGNAL'
  | 'INSUFFICIENT_DATA'
  | 'STALE_DATA'
  | 'DATA_QUALITY_ERROR';

export interface HealthResponse {
  status: string;
  application: string;
  mode: string;
  ai: boolean;
  paper_trading: boolean;
  order_execution: boolean;
  timestamp: string;
}

export interface ProviderStatus {
  name: string;
  configured: boolean;
  available?: boolean;
  purpose?: string;
  note: string;
}

export interface ProvidersResponse {
  providers: ProviderStatus[];
  checked_at: string;
}

export interface Candle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandlesResponse {
  symbol: string;
  market: Market;
  exchange: string | null;
  interval: string;
  source: string;
  is_adjusted: boolean;
  freshness: string;
  is_stale: boolean;
  history_truncated: boolean;
  history_pages: number | null;
  last_candle_at: string;
  count: number;
  candles: Candle[];
  warnings: string[];
}

export interface SignalCondition {
  name: string;
  passed: boolean;
  observed: number | string | null;
  threshold: number | string | null;
  explanation: string;
}

export interface StrategySignal {
  symbol: string;
  market: Market;
  strategy: string;
  strategy_version: string;
  state: SignalState;
  as_of: string | null;
  entry_reference: number | null;
  stop_reference: number | null;
  risk_per_unit: number | null;
  conditions: SignalCondition[];
  explanation: string;
  data_source: string | null;
}

export type IndicatorValues = Record<string, number | null>;

export interface LatestOhlcv {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface AnalysisResponse {
  symbol: string;
  market: Market;
  exchange: string | null;
  interval: string;
  source: string;
  is_adjusted: boolean;
  is_stale: boolean;
  history_truncated: boolean;
  history_pages: number | null;
  as_of: string;
  latest: LatestOhlcv;
  indicators: IndicatorValues;
  strategy: StrategySignal;
  warnings: string[];
  candles: Candle[];
}

export interface IndicatorSeriesRow {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  [indicator: string]: number | string | null;
}

export interface IndicatorSeriesResponse {
  symbol: string;
  market: Market;
  exchange: string | null;
  interval: string;
  source: string;
  is_adjusted: boolean;
  is_stale: boolean;
  as_of: string;
  count: number;
  series: IndicatorSeriesRow[];
}

export type ScannerStrategy = Partial<StrategySignal> & { state: SignalState };

export interface ScannerItem {
  symbol: string;
  market: Market;
  source?: string;
  last_close?: number;
  is_adjusted?: boolean;
  is_stale?: boolean;
  strategy: ScannerStrategy;
  error?: string;
}

export interface ScannerResponse {
  items: ScannerItem[];
  count: number;
  note: string;
}

export interface WatchlistItem {
  id: number;
  symbol: string;
  market: Market;
  exchange: string;
  display_name: string;
  created_at: string;
}

export interface WatchlistResponse {
  items: WatchlistItem[];
}

export interface AddWatchlistRequest {
  symbol: string;
  market: Market;
  exchange?: string | null;
  display_name?: string | null;
}

export interface NewsItem {
  id: string;
  title: string;
  url: string;
  publisher: string | null;
  published_at: string | null;
  retrieved_at: string;
  summary: string | null;
  category: string;
  source: string;
  related_symbols: string[];
  official: boolean;
}

export interface NewsProviderState {
  enabled?: boolean;
  configured_feeds?: number;
  error?: string | null;
  errors?: string[];
  note?: string;
}

export interface NewsResponse {
  symbol: string;
  market: Market;
  items: NewsItem[];
  count: number;
  providers: Record<string, NewsProviderState>;
  note: string;
}

export interface BacktestRequest {
  symbol: string;
  market: Market;
  exchange?: string | null;
  interval?: string;
  days?: number;
  provider?: string;
  initial_capital?: number;
  risk_fraction?: number;
  cost_bps_per_side?: number;
  max_position_fraction?: number;
}

export interface BacktestTrade {
  signal_time: string;
  entry_time: string;
  exit_time: string;
  entry_price: number;
  exit_price: number;
  quantity: number;
  gross_pnl: number;
  total_costs: number;
  net_pnl: number;
  exit_reason: string;
}

export interface EquityPoint {
  timestamp: string;
  equity: number;
}

export interface BacktestResult {
  initial_capital: number;
  final_equity: number;
  net_return_pct: number;
  trade_count: number;
  win_rate_pct: number | null;
  profit_factor: number | 'infinite' | null;
  expectancy_per_trade: number | null;
  max_drawdown_pct: number | null;
  sharpe_daily_annualized: number | null;
  sortino_daily_annualized: number | null;
  cost_bps_per_side: number;
  trades: BacktestTrade[];
  equity_curve: EquityPoint[];
  limitations: string[];
  symbol: string;
  market: Market;
  source: string;
  strategy: string;
  strategy_version: string;
  data_adjusted: boolean;
}

export interface RiskRequest {
  capital: number;
  risk_fraction: number;
  entry: number;
  stop: number;
  lot_size?: number;
  max_position_fraction?: number;
}

export interface RiskResult {
  risk_budget: number;
  risk_per_unit: number;
  quantity: number;
  position_value: number;
  planned_loss: number;
  capital_limited: boolean;
}

export interface Transaction {
  id: number;
  symbol: string;
  market: Market;
  side: Side;
  quantity: number;
  price: number;
  trade_time: string;
  currency: string;
  fees: number;
  notes: string | null;
}

export interface TransactionsResponse {
  transactions: Transaction[];
  mode: string;
}

export interface TransactionRequest {
  symbol: string;
  market: Market;
  side: Side;
  quantity: number;
  price: number;
  trade_time: string;
  currency: string;
  fees: number;
  notes?: string | null;
}

export interface Position {
  market: Market;
  symbol: string;
  currency: string;
  quantity: number;
  cost_basis: number;
  realised_pnl: number;
  average_cost: number;
}

export interface PositionsResponse {
  positions: Position[];
  accounting_method: string;
  note: string;
}

export interface SignalsHistoryResponse {
  signals: StrategySignal[];
}

export type TechnicalAction = 'Buy' | 'Sell' | 'Neutral';

export type TechnicalAssessment = 'Strong Buy' | 'Buy' | 'Neutral' | 'Sell' | 'Strong Sell';

export interface TechnicalRow {
  name: string;
  field: string;
  value: number | null;
  action: TechnicalAction;
}

export interface TechnicalCounts {
  action: TechnicalAssessment;
  score: number;
  sell: number;
  neutral: number;
  buy: number;
}

export interface TechnicalSummaryResponse {
  symbol: string;
  market: Market;
  exchange: string | null;
  interval: string;
  source: string;
  is_adjusted: boolean;
  is_stale: boolean;
  as_of: string;
  close: number;
  oscillators: TechnicalRow[];
  moving_averages: TechnicalRow[];
  summary: {
    oscillators: TechnicalCounts;
    moving_averages: TechnicalCounts;
    overall: TechnicalCounts;
  };
  method: string;
}

export interface ApiErrorPayload {
  detail?: string;
}
