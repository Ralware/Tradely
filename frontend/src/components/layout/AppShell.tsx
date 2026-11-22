import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';

export function AppShell() {
  return (
    <div className="flex h-dvh min-h-0 w-full flex-col-reverse gap-2 overflow-hidden bg-terminal-bg p-2 text-terminal-text sm:flex-row sm:gap-3 sm:p-3">
      <Sidebar />
      <main className="min-h-0 min-w-0 flex-1 overflow-hidden" id="main-content">
        <div className="h-full min-w-0 overflow-auto overscroll-contain rounded-[24px]">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
