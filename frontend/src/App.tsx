import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { WatchlistPage } from './pages/WatchlistPage';
import { AnalysisPage } from './pages/AnalysisPage';
import { MarketsPage } from './pages/MarketsPage';
import { PortfolioPage } from './pages/PortfolioPage';
import { BacktestingPage } from './pages/BacktestingPage';
import { SettingsPage } from './pages/SettingsPage';
import { NotFoundPage } from './pages/NotFoundPage';

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<WatchlistPage />} />
        <Route path="analysis" element={<AnalysisPage />} />
        <Route path="markets" element={<MarketsPage />} />
        <Route path="portfolio" element={<PortfolioPage />} />
        <Route path="backtesting" element={<BacktestingPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="stocks" element={<Navigate to="/analysis" replace />} />
        <Route path="crypto" element={<Navigate to="/analysis" replace />} />
        <Route path="dashboard" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
