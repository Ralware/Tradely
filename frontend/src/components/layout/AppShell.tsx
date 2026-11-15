import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';

export function AppShell() {
  return (
    <div className="flex h-screen w-screen flex-col-reverse sm:flex-row overflow-hidden bg-terminal-bg text-terminal-text">
      {/* Compact Navigation Rail (Desktop vertical rail / Mobile bottom bar) */}
      <Sidebar />

      {/* Main Content Area */}
      <main className="flex-1 min-w-0 h-full overflow-hidden flex flex-col">
        <div className="flex-1 min-w-0 overflow-y-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
