import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSelectedInstrument } from "../contexts/SelectedInstrumentContext";
import { AnalysisWorkspace } from "../components/analysis/AnalysisWorkspace";
import { AnalysisWatchlist } from "../components/analysis/AnalysisWatchlist";
import type { WatchlistItem } from "../types/api";
import { instrumentPath } from "../utils/navigation";
import { Icon } from "../components/common/Icon";

export function AnalysisPage() {
  const navigate = useNavigate();
  const selected = useSelectedInstrument();
  const [drawerOpen, setDrawerOpen] = useState(false);

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
    <div className="flex h-full w-full overflow-hidden">
      {/* Center Main Analysis Workspace */}
      <div className="flex-1 min-w-0 h-full overflow-y-auto px-3 py-3 lg:px-4">
        {/* Mobile/Tablet Right-Watchlist Toggle Button */}
        <div className="mb-2 flex justify-end lg:hidden">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className="flex items-center gap-1.5 rounded border border-terminal-border bg-terminal-panel px-2.5 py-1 text-2xs font-medium text-terminal-muted hover:text-white"
          >
            <Icon name="portfolio" size={13} />
            <span>Watchlist</span>
          </button>
        </div>

        <AnalysisWorkspace />
      </div>

      {/* Desktop Fixed Right-Hand Watchlist Sidebar */}
      <aside className="hidden lg:block w-72 shrink-0 h-full">
        <AnalysisWatchlist
          selectedInstrumentId={selected.instrumentId}
          onSelectInstrument={handleSelectInstrument}
        />
      </aside>

      {/* Mobile/Tablet Watchlist Slide-out Drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <div
            className="fixed inset-0 bg-black/70 backdrop-blur-xs transition-opacity"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="relative ml-auto flex h-full w-80 max-w-[85vw] flex-col bg-black shadow-2xl">
            <AnalysisWatchlist
              selectedInstrumentId={selected.instrumentId}
              onSelectInstrument={handleSelectInstrument}
              onClose={() => setDrawerOpen(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
