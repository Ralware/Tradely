import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-screen bg-terminal-bg">
      <div className="flex min-h-screen">
        <aside className="hidden w-60 shrink-0 lg:block">
          <div className="sticky top-0 h-screen">
            <Sidebar />
          </div>
        </aside>

        {menuOpen ? (
          <div className="fixed inset-0 z-40 lg:hidden">
            <button
              type="button"
              aria-label="Close navigation menu"
              className="absolute inset-0 bg-black/60"
              onClick={() => setMenuOpen(false)}
            />
            <div className="absolute inset-y-0 left-0 w-64 shadow-2xl">
              <Sidebar onNavigate={() => setMenuOpen(false)} />
            </div>
          </div>
        ) : null}

        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar onOpenMenu={() => setMenuOpen(true)} />
          <main className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-5 lg:px-6">
            <Outlet />
          </main>
          <footer className="border-t border-terminal-border px-4 py-4 text-[11px] leading-relaxed text-terminal-muted lg:px-6">
            Research tool only. Signals are deterministic but are not proof of future performance.
            Data providers can be delayed, incomplete or unavailable. Verify prices, corporate
            actions and event details at the original source. Tradely does not place orders.
          </footer>
        </div>
      </div>
    </div>
  );
}
