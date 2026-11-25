import { Outlet } from 'react-router-dom';
import { TopNav } from './TopNav';

export function AppShell() {
  return (
    <div className="flex h-dvh min-h-0 w-full flex-col overflow-hidden bg-terminal-bg text-terminal-text">
      <TopNav />
      <main className="app-main min-h-0 min-w-0 flex-1 overflow-hidden" id="main-content">
        <Outlet />
      </main>
    </div>
  );
}
