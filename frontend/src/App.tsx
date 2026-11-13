import { Route, Routes } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { DashboardPage } from './pages/DashboardPage';
import { MarketsPage } from './pages/MarketsPage';
import { StockAnalysisPage } from './pages/StockAnalysisPage';
import { CryptoAnalysisPage } from './pages/CryptoAnalysisPage';
import { PortfolioPage } from './pages/PortfolioPage';
import { BacktestingPage } from './pages/BacktestingPage';
import { SettingsPage } from './pages/SettingsPage';
import { NotFoundPage } from './pages/NotFoundPage';

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="markets" element={<MarketsPage />} />
        <Route path="stocks" element={<StockAnalysisPage />} />
        <Route path="crypto" element={<CryptoAnalysisPage />} />
        <Route path="portfolio" element={<PortfolioPage />} />
        <Route path="backtesting" element={<BacktestingPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
