export type Market = 'india' | 'global' | 'crypto';

export type TransactionIntent = 'BUY' | 'SELL' | 'SELL_SHORT' | 'BUY_TO_COVER';
export type Side = 'BUY' | 'SELL';
export type DirectionMode = 'long_only' | 'short_only' | 'long_short';
export type PositionDirection = 'LONG' | 'SHORT';
export type SignalState =
  | 'BUY'
  | 'SELL'
  | 'SELL_SHORT'
  | 'BUY_TO_COVER'
  | 'WAIT'
  | 'NO_SIGNAL'
  | 'INSUFFICIENT_DATA'
  | 'STALE_DATA'
  | 'DATA_QUALITY_ERROR';

export type AssetType = 'equity' | 'crypto';

export type QuoteFreshness =
  | 'live'
  | 'delayed'
  | 'eod'
  | 'historical'
  | 'cached'
  | 'stale'
  | 'unavailable';

export type QuoteType =
  | 'real_time'
  | 'delayed'
  | 'last_available'
  | 'previous_close'
  | 'end_of_day'
  | 'historical'
  | 'cached'
  | 'stale'
  | 'unavailable';

export interface TradingQuantityRules {
  quantity_step: number | null;
  min_quantity: number | null;
  fractional: boolean | null;
  min_notional: number | null;
  source: string | null;
}

export interface InstrumentCapabilities {
  instrument_id: string;
  status: string;
  quote_available: boolean;
  real_time_streaming: boolean;
  historical_ohlcv: boolean;
  supported_intervals: string[];
  adjusted_history: boolean;
  technicals: boolean;
  backtesting_eligible: boolean;
  corporate_events: boolean;
  news: boolean;
  provider: string;
  provider_key: string;
  quote_freshness: string;
  quantity: TradingQuantityRules;
  data_limitations: string[];
}

export interface Instrument {
  instrument_id: string;
  symbol: string;
  name: string;
  market: Market;
  exchange: string;
  currency: string;
  asset_type: AssetType;
  provider: string;
  provider_symbol: string;
  display_name?: string | null;
  base_currency?: string | null;
  quote_currency?: string | null;
  settlement_currency?: string | null;
  trading_pair?: string | null;
  provider_instrument_id?: string | null;
  supported_intervals?: string[];
  status?: string;
  catalogue_source?: string | null;
  catalogue_updated_at?: string | null;
  is_catalogue?: boolean;
  aliases?: string[];
  capabilities?: InstrumentCapabilities;
  asset_label?: string;
}

export type InstrumentRecognitionStatus = 'resolved' | 'ambiguous' | 'not_found' | 'unsupported';

export type InstrumentMatchType =
  | 'instrument_id'
  | 'symbol'
  | 'provider_symbol'
  | 'alias'
  | 'name'
  | 'partial_symbol'
  | 'partial_name';

export interface InstrumentCandidate {
  instrument_id: string;
  symbol: string;
  name: string;
  display_name?: string | null;
  market: Market;
  exchange: string;
  currency: string;
  asset_type: AssetType;
  provider: string;
  provider_symbol: string;
  base_currency?: string | null;
  quote_currency?: string | null;
  trading_pair?: string | null;
  status?: string;
  score?: number;
  match_type?: InstrumentMatchType;
  asset_label?: string;
}

export interface RecognizedAsset {
  symbol: string;
  asset_class: string;
  base_currency: string;
  quote_currency: string;
  trading_pair: string;
  reason: string;
}

export interface Quote {
  instrument_id: string;
  symbol: string;
  name?: string;
  market: Market;
  exchange: string;
  currency: string;
  asset_type?: AssetType;
  provider: string;
  provider_symbol?: string;
  price: number | null;
  previous_close: number | null;
  day_change: number | null;
  day_change_pct: number | null;
  day_high: number | null;
  day_low: number | null;
  volume: number | null;
  quote_time: string | null;
  retrieved_at: string;
  quote_type: QuoteType;
  freshness: QuoteFreshness;
  is_stale: boolean;
  age_seconds: number | null;
  market_status: string;
  transport?: string;
  is_adjusted?: boolean | null;
  provider_freshness?: string | null;
  error: string | null;
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
  instrument?: Instrument | null;
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
  instrument_id?: string;
  strategy: string;
  strategy_version: string;
  direction_mode?: DirectionMode;
  direction?: PositionDirection | null;
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
  instrument?: Instrument | null;
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
  instrument?: Instrument | null;
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
  instrument_id?: string;
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
  instrument_id?: string;
  currency?: string;
  asset_type?: AssetType;
  provider?: string;
  provider_symbol?: string;
  name?: string;
  is_held?: boolean;
  held_quantity?: number;
}

export interface WatchlistResponse {
  items: WatchlistItem[];
}

export interface AddWatchlistRequest {
  instrument_id?: string | null;
  symbol?: string;
  market?: Market;
  exchange?: string | null;
  display_name?: string | null;
}

export interface BacktestRequest {
  instrument_id?: string;
  symbol?: string;
  market?: Market;
  exchange?: string | null;
  interval?: string;
  days?: number;
  provider?: string;
  initial_capital?: number;
  risk_fraction?: number;
  cost_bps_per_side?: number;
  commission_bps_per_side?: number;
  slippage_bps_per_side?: number;
  max_position_fraction?: number;
  direction_mode?: DirectionMode;
  strategy_config?: StrategyConfig;
}

export interface StrategyConfig {
  sma_fast_period: number; sma_slow_period: number; rsi_period: number; rsi_threshold: number;
  adx_period: number; min_adx: number; atr_period: number; initial_stop_atr: number;
  trailing_stop_atr: number; donchian_entry_period: number; rvol_period: number;
  min_rvol: number; donchian_exit_period: number;
}

export interface BacktestTrade {
  direction: PositionDirection;
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
  gross_pnl: number;
  total_maker_fees: number;
  total_taker_fees: number;
  total_fees: number;
  strategy_config: StrategyConfig;
  strategy_indicators: Record<string, number | null>;
  date_range?: { start: string; end: string };
  execution_assumptions?: Record<string, number>;
  executed_at?: string;
  direction_mode?: DirectionMode;
  initial_capital: number;
  final_equity: number;
  net_profit_loss: number;
  net_return_pct: number;
  trade_count: number;
  win_rate_pct: number | null;
  average_winning_trade: number | null;
  average_losing_trade: number | null;
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
  instrument?: Instrument | null;
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
  direction?: PositionDirection;
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
  direction?: PositionDirection;
}

export interface Transaction {
  id: number;
  symbol: string;
  market: Market;
  side: Side;
  intent?: TransactionIntent;
  quantity: number;
  price: number;
  amount?: number;
  actual_amount?: number;
  remaining_amount?: number;
  trade_time: string;
  currency: string;
  fees: number;
  notes: string | null;
  instrument_id?: string;
  instrument_name?: string;
  name?: string;
  exchange?: string;
  asset_type?: AssetType;
  provider?: string;
  provider_symbol?: string;
  quote_provider?: string;
  quote_time?: string | null;
  quote_type?: string;
  quote_status?: string;
  quote_currency?: string;
  realised_pnl?: number;
  unit_cost?: number;
  cost_basis_added?: number;
  cost_basis_consumed?: number;
  proceeds?: number;
}

export interface TransactionsResponse {
  transactions: Transaction[];
  mode: string;
  accounting_method?: string;
  order_execution?: boolean;
}

export interface TransactionRequest {
  instrument_id: string;
  intent: TransactionIntent;
  side?: Side;
  amount: number;
  currency: string;
  fees: number;
  trade_time: string;
  notes?: string | null;
  idempotency_key?: string | null;
}

export interface TradingRules {
  quantity_step: number;
  min_quantity: number;
  max_quantity: number | null;
  min_notional: number;
  fractional: boolean;
  source: string;
  is_fallback?: boolean;
}

export interface TransactionPreviewResponse {
  valid: boolean;
  error: string | null;
  side?: Side;
  intent?: TransactionIntent;
  instrument?: Instrument;
  quote?: Quote;
  trading_rules?: TradingRules;
  requested_amount?: number;
  quantity?: number;
  actual_amount?: number;
  remaining_amount?: number;
  fees?: number;
  total_cash_cost?: number | null;
  net_proceeds?: number | null;
  available_quantity?: number | null;
  max_sell_amount?: number | null;
  max_sell_quantity?: number | null;
  max_close_amount?: number | null;
  remaining_holding_quantity?: number | null;
  accounting_note?: string | null;
  warnings?: string[];
  price_note?: string;
}

export interface Position {
  instrument_id: string;
  symbol: string;
  name: string;
  market: Market;
  exchange: string;
  currency: string;
  asset_type: AssetType;
  provider: string;
  provider_symbol: string;
  position_side?: PositionDirection | null;
  direction?: PositionDirection | null;
  quantity: number;
  absolute_quantity?: number;
  average_cost: number;
  cost_basis: number;
  realised_pnl: number;
  current_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  return_pct: number | null;
  day_change: number | null;
  day_change_pct: number | null;
  total_bought: number;
  total_sold: number;
  fees_total: number;
  buy_fees: number;
  sell_fees: number;
  lot_count: number;
  quote: Quote | null;
  valuation_error: string | null;
}

export interface CurrencySummary {
  currency: string;
  total_invested: number;
  market_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  unrealized_pnl_pct: number | null;
  realized_pnl_pct: number | null;
  total_pnl_pct: number | null;
  open_positions: number;
  long_positions?: number;
  short_positions?: number;
  closed_positions: number;
  priced_positions: number;
  unpriced_positions: number;
  priced_invested: number;
  unpriced_invested: number;
  short_proceeds_basis?: number;
  priced_short_proceeds_basis?: number;
  short_market_value?: number;
  gross_market_value?: number;
  transaction_fees: number;
  latest_quote_at: string | null;
}

export interface PortfolioSummary {
  base_currency: string;
  currencies: CurrencySummary[];
  currency_conversion: string;
  note: string;
  open_positions: number;
  closed_positions: number;
  instruments: number;
  transactions: number;
}

export interface PositionsResponse {
  positions: Position[];
  summary?: PortfolioSummary;
  accounting_method: string;
  note: string;
}

export interface PositionLot {
  transaction_id: number;
  acquired_at: string;
  original_quantity: number;
  remaining_quantity: number;
  unit_cost: number;
  unit_proceeds?: number | null;
  price: number;
  fees_allocated: number;
  remaining_cost_basis: number;
}

export interface PositionTotals {
  total_bought: number;
  total_sold: number;
  buy_fees: number;
  sell_fees: number;
  fees_total: number;
  realised_pnl: number;
  remaining_cost_basis: number;
  average_cost: number;
  position_side?: PositionDirection | null;
  long_lot_count?: number;
  short_lot_count?: number;
}

export interface PositionDetailResponse {
  instrument_id: string;
  position: Position;
  purchase_history: Transaction[];
  sale_history: Transaction[];
  short_history?: Transaction[];
  transactions: Transaction[];
  remaining_lots: PositionLot[];
  totals: PositionTotals;
  candles: Candle[];
  candle_source: string | null;
  candle_error: string | null;
  currency_conversion: string;
  accounting_method: string;
}

export interface AddTransactionResponse {
  transaction: Transaction;
  instrument: Instrument | null;
  quote: Quote | null;
  quote_error: string | null;
  quote_available: boolean;
  calculation?: Record<string, unknown> | null;
  trading_rules?: TradingRules | null;
  duplicate?: boolean;
  position: Position | null;
  positions: Position[];
  summary: PortfolioSummary;
  transactions: Transaction[];
  accounting_method: string;
  order_execution: boolean;
  price_note?: string;
}

export interface InstrumentResolutionResponse {
  query: string;
  normalized: string;
  status: InstrumentRecognitionStatus;
  message: string | null;
  instrument: Instrument | null;
  candidates: InstrumentCandidate[];
  items?: InstrumentCandidate[];
  count: number;
  recognized?: RecognizedAsset | null;
  resolved: boolean;
}

export interface InstrumentSearchResponse extends InstrumentResolutionResponse {
  items: InstrumentCandidate[];
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
  instrument?: Instrument | null;
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

