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
      className="flex h-12 sm:h-screen w-full sm:w-[60px] shrink-0 flex-row sm:flex-col items-center justify-around sm:justify-start border-t sm:border-t-0 sm:border-r border-terminal-border bg-black py-0 sm:py-4 select-none z-30"
      aria-label="Application Navigation"
    >
      <nav className="flex w-full sm:w-auto flex-row sm:flex-col items-center justify-around sm:justify-start gap-1 sm:gap-2" aria-label="Main Navigation">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            title={item.label}
            className={({ isActive }) =>
              cn(
                'group relative flex h-10 w-10 items-center justify-center rounded-sm transition-colors',
                isActive
                  ? 'bg-black text-terminal-accent after:absolute after:bottom-0 sm:after:bottom-auto after:left-2 sm:after:left-0 sm:after:top-2 sm:after:bottom-2 after:right-2 sm:after:right-auto after:h-[2px] sm:after:h-auto sm:after:w-[3px] after:bg-terminal-accent'
                  : 'text-terminal-muted hover:bg-white/[0.05] hover:text-white',
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon
                  name={item.icon}
                  size={19}
                  className={cn(
                    'transition-colors',
                    isActive ? 'text-terminal-accent' : 'text-terminal-muted group-hover:text-white',
                  )}
                />
                {/* Floating Tooltip on Desktop */}
                <span className="pointer-events-none absolute left-full ml-2 z-50 hidden rounded bg-black border border-terminal-border px-2 py-1 text-2xs font-medium text-white shadow-lg whitespace-nowrap group-hover:block">
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
