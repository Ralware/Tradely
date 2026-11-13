import { AnalysisWorkspace } from '../components/analysis/AnalysisWorkspace';

export function StockAnalysisPage() {
  return (
    <AnalysisWorkspace
      variant="stocks"
      title="Stock analysis"
      subtitle="Rule-based signals, indicators, risk sizing, news and corporate events for Indian and international equities. Every calculation is produced by the FastAPI backend."
    />
  );
}
