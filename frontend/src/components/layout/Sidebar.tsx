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

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Watchlist', icon: 'dashboard', end: true },
  { to: '/analysis', label: 'Analysis', icon: 'chart' },
  { to: '/portfolio', label: 'Portfolio', icon: 'portfolio' },
  { to: '/backtesting', label: 'Backtesting', icon: 'flask' },
];

interface SidebarProps {
  onNavigate?: () => void;
  /** Optional bottom slot for settings, connection status, or profile */
  footerSlot?: React.ReactNode;
}

export function Sidebar({ onNavigate, footerSlot }: SidebarProps) {
  return (
    <nav
      aria-label="Primary Navigation"
      className={cn(
        'z-30 flex shrink-0 select-none border-terminal-border bg-black',
        // Mobile: bottom bar | Desktop: left vertical rail
        'h-14 w-full flex-row items-center justify-around border-t px-2',
        'sm:h-screen sm:w-[60px] sm:flex-col sm:justify-center sm:border-r sm:border-t-0 sm:px-0 sm:py-4',
      )}
    >
      {/* Navigation Links — vertically centered on desktop via sm:my-auto */}
      <div className="flex w-full flex-row items-center justify-around gap-1 sm:my-auto sm:w-auto sm:flex-col sm:justify-center sm:gap-3">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            aria-label={item.label}
            className={({ isActive }) =>
              cn(
                'group relative flex h-10 w-10 items-center justify-center rounded-sm transition-colors duration-150',
                'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-terminal-accent',
                isActive
                  ? 'bg-white/[0.04] text-terminal-accent'
                  : 'text-terminal-muted hover:bg-white/[0.05] hover:text-white',
              )
            }
          >
            {({ isActive }) => (
              <>
                {/* Active Indicator Pill (Bottom on mobile, Left on desktop) */}
                {isActive && (
                  <span
                    aria-hidden="true"
                    className={cn(
                      'absolute bg-terminal-accent',
                      'bottom-0 left-2 right-2 h-[2px]',
                      'sm:bottom-2 sm:left-0 sm:right-auto sm:top-2 sm:h-auto sm:w-[3px] sm:rounded-r-xs',
                    )}
                  />
                )}

                <Icon
                  name={item.icon}
                  size={19}
                  aria-hidden="true"
                  className={cn(
                    'shrink-0 transition-transform duration-150 group-active:scale-95',
                    isActive
                      ? 'text-terminal-accent'
                      : 'text-terminal-muted group-hover:text-white',
                  )}
                />

                {/* Desktop Tooltip (Hover + Keyboard Focus) */}
                <span
                  role="tooltip"
                  className={cn(
                    'pointer-events-none absolute left-full z-50 ml-3 hidden whitespace-nowrap',
                    'rounded border border-terminal-border bg-black/95 px-2.5 py-1',
                    'text-[11px] font-medium tracking-wide text-white shadow-xl backdrop-blur-xs',
                    'sm:group-hover:block sm:group-focus-visible:block',
                  )}
                >
                  {item.label}
                </span>
              </>
            )}
          </NavLink>
        ))}
      </div>

      {/* Optional Footer Actions pinned to bottom on desktop */}
      {footerSlot && (
        <div className="hidden sm:flex sm:flex-col sm:items-center sm:gap-2">
          {footerSlot}
        </div>
      )}
    </nav>
  );
}