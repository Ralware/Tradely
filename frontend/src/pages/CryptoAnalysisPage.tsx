import { AnalysisWorkspace } from '../components/analysis/AnalysisWorkspace';

export function CryptoAnalysisPage() {
  return (
    <AnalysisWorkspace
      variant="crypto"
      title="Crypto analysis"
      subtitle="Binance Spot OHLCV, the backend daily strategy, indicator series and risk sizing for crypto pairs. Signals are deterministic and research-only."
    />
  );
}
