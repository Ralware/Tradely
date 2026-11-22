import { NavLink } from 'react-router-dom';
import { cn } from '../../utils/format';
import { Icon } from '../common/Icon';
import type { IconName } from '../common/Icon';

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  end?: boolean;
}

const navItems: NavItem[] = [
  { to: '/', label: 'Watchlist', icon: 'dashboard', end: true },
  { to: '/analysis', label: 'Analysis', icon: 'chart' },
  { to: '/portfolio', label: 'Portfolio', icon: 'portfolio' },
  { to: '/backtesting', label: 'Backtesting', icon: 'flask' },
];

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <aside
      className="app-sidebar z-30 flex w-full shrink-0 flex-row items-center border border-terminal-border bg-terminal-panelAlt px-2 py-1.5 sm:h-[calc(100dvh-24px)] sm:w-[76px] sm:flex-col sm:justify-center sm:px-2.5 sm:py-4"
      aria-label="Application navigation"
    >
      <nav className="flex min-w-0 flex-1 flex-row items-center justify-around gap-1 sm:flex-col sm:items-center sm:justify-center sm:gap-3" aria-label="Main navigation">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            aria-label={item.label}
            title={item.label}
            className={({ isActive }) => cn(
              'app-sidebar-link group relative flex h-11 min-w-10 flex-1 flex-col items-center justify-center gap-1 rounded-full px-1 text-xs transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-terminal-accent sm:h-12 sm:w-12 sm:flex-none sm:gap-0 sm:px-0',
              isActive
                ? 'bg-terminal-accentSoft text-terminal-text ring-1 ring-[#2a3a55]'
                : 'text-terminal-muted hover:bg-white/[0.06] hover:text-terminal-text',
            )}
          >
            {({ isActive }) => (
              <>
                <Icon name={item.icon} size={18} className={cn('shrink-0', isActive ? 'text-terminal-accent' : 'text-current')} />
                <span className="text-[9px] leading-none sm:hidden">{item.label}</span>
                <span className="pointer-events-none absolute left-full z-50 ml-2 hidden whitespace-nowrap rounded-full border border-terminal-border bg-terminal-panelAlt px-3 py-1.5 text-2xs text-terminal-text opacity-0 shadow-lg transition-opacity group-hover:block group-hover:opacity-100 group-focus-visible:block group-focus-visible:opacity-100 sm:block">
                  {item.label}
                </span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
