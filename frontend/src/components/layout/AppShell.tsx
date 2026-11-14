import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { MarketSidebar } from './MarketSidebar';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [watchlistOpen, setWatchlistOpen] = useState(false);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-terminal-bg">
      <TopBar onOpenMenu={() => setMenuOpen(true)} onOpenWatchlist={() => setWatchlistOpen(true)} />

      <div className="flex min-h-0 flex-1">
        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1400px] px-3 py-3 lg:px-4">
            <Outlet />
          </div>
          <footer className="border-t border-terminal-border px-4 py-2 text-2xs text-terminal-muted">
            Research Tool Only · No Order Execution · Verify Prices and Corporate Actions at the
            Original Source
          </footer>
        </main>

        <aside className="hidden w-[340px] shrink-0 border-l border-terminal-border bg-terminal-panelAlt xl:block">
          <div className="h-full overflow-y-auto">
            <MarketSidebar />
          </div>
        </aside>
      </div>

      {menuOpen ? (
        <div className="fixed inset-0 z-40 xl:hidden">
          <button
            type="button"
            aria-label="Close Navigation"
            className="absolute inset-0 bg-black/70"
            onClick={() => setMenuOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 w-60 border-r border-terminal-border">
            <Sidebar onNavigate={() => setMenuOpen(false)} />
          </div>
        </div>
      ) : null}

      {watchlistOpen ? (
        <div className="fixed inset-0 z-40 xl:hidden">
          <button
            type="button"
            aria-label="Close Watchlist"
            className="absolute inset-0 bg-black/70"
            onClick={() => setWatchlistOpen(false)}
          />
          <div className="absolute inset-y-0 right-0 w-[min(92vw,360px)] overflow-y-auto border-l border-terminal-border bg-terminal-panelAlt">
            <MarketSidebar />
          </div>
        </div>
      ) : null}
    </div>
  );
}
