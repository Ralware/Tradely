import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSelectedInstrument } from "../contexts/SelectedInstrumentContext";
import { AnalysisWorkspace } from "../components/analysis/AnalysisWorkspace";
import { AnalysisWatchlist } from "../components/analysis/AnalysisWatchlist";
import { StockNewsPreview } from "../components/analysis/StockNewsPreview";
import type { WatchlistItem } from "../types/api";
import { instrumentPath } from "../utils/navigation";
import { Icon } from "../components/common/Icon";

export function AnalysisPage() {
  const navigate = useNavigate();
  const selected = useSelectedInstrument();
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    if (!drawerOpen) return undefined;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setDrawerOpen(false);
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [drawerOpen]);

  function handleSelectInstrument(item: WatchlistItem) {
    setDrawerOpen(false);
    if (item.instrument_id) {
      navigate(
        instrumentPath(
          { instrument_id: item.instrument_id, market: item.market },
          { interval: selected.interval, days: selected.days },
        ),
      );
    } else {
      navigate(
        instrumentPath(
          {
            instrument_id: `${item.market}:${item.exchange}:${item.symbol}`,
            market: item.market,
          },
          { interval: selected.interval, days: selected.days },
        ),
      );
    }
  }

  return (
    <div className="tv-analysis-page flex h-full w-full overflow-hidden">
      {/* Center Main Analysis Workspace */}
      <div className="tv-analysis-main h-full min-w-0 flex-1 overflow-y-auto px-3 py-3 lg:px-4">
        {/* Mobile/Tablet Right-Watchlist Toggle Button */}
        <div className="mb-2 flex justify-end xl:hidden">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className="tv-analysis-watchlist-toggle inline-flex items-center gap-1.5 rounded-md border border-terminal-border bg-terminal-panel px-2.5 py-1.5 text-2xs font-medium text-terminal-muted transition-colors hover:text-terminal-text"
          >
            <Icon name="star" size={13} />
            <span>Watchlist</span>
          </button>
        </div>

        <AnalysisWorkspace />
        {selected.instrumentId ? (
          <div className="mt-3 w-full">
            <StockNewsPreview instrumentId={selected.instrumentId} symbol={selected.symbol} />
          </div>
        ) : null}
      </div>

      {/* Desktop Fixed Right-Hand Watchlist Sidebar */}
      <aside className="tv-watchlist-panel hidden h-[calc(100%-16px)] w-72 shrink-0 overflow-hidden xl:my-2 xl:mr-2 xl:flex xl:flex-col">
        <AnalysisWatchlist
          selectedInstrumentId={selected.instrumentId}
          onSelectInstrument={handleSelectInstrument}
        />
      </aside>

      {/* Mobile/Tablet Watchlist Slide-out Drawer */}
      {drawerOpen ? (
        <div className="fixed inset-0 z-50 flex xl:hidden">
          <div
            className="fixed inset-0 bg-black"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="tv-analysis-watchlist-drawer relative ml-auto flex h-full w-80 max-w-[85vw] flex-col overflow-hidden border-l border-terminal-border bg-terminal-panel">
            <AnalysisWatchlist
              selectedInstrumentId={selected.instrumentId}
              onSelectInstrument={handleSelectInstrument}
              onClose={() => setDrawerOpen(false)}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
