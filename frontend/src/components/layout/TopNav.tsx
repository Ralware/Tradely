import { NavLink, useNavigate } from 'react-router-dom';
import { useSelectedInstrument } from '../../contexts/SelectedInstrumentContext';
import type { Instrument } from '../../types/api';
import { instrumentPath } from '../../utils/navigation';
import { cn } from '../../utils/format';
import { Icon } from '../common/Icon';
import type { IconName } from '../common/Icon';
import { InstrumentSearch } from '../instruments/InstrumentSearch';

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  end?: boolean;
}

const navItems: NavItem[] = [
  { to: '/', label: 'Watchlist', icon: 'star', end: true },
  { to: '/analysis', label: 'Analytics', icon: 'chart' },
  { to: '/portfolio', label: 'Portfolio', icon: 'portfolio' },
  { to: '/backtesting', label: 'Backtesting', icon: 'flask' },
  { to: '/news', label: 'News', icon: 'news' },
];

export function TopNav() {
  const navigate = useNavigate();
  const selected = useSelectedInstrument();

  function openInstrument(instrument: Instrument) {
    navigate(
      instrumentPath(instrument, {
        interval: selected.interval,
        days: selected.days,
      }),
    );
  }

  return (
    <header className="app-topbar relative z-40 flex h-[68px] shrink-0 items-center justify-center px-3 sm:px-4">
      <NavLink
        to="/"
        end
        className="absolute left-4 hidden shrink-0 text-sm font-semibold tracking-[0.02em] text-terminal-text lg:block"
      >
        Tradely
      </NavLink>

      <div className="tradely-nav-shell flex min-w-0 max-w-full items-center gap-2">
      <nav
        aria-label="Main navigation"
        className="flex min-w-0 items-center justify-center gap-0.5 overflow-x-auto"
      >
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                'relative flex h-9 shrink-0 items-center gap-1.5 rounded-full px-3 text-xs transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-terminal-accent',
                isActive
                  ? 'bg-[#101b29] text-terminal-accent'
                  : 'text-terminal-muted hover:bg-[#101010] hover:text-terminal-text',
              )
            }
          >
            <>
              <Icon name={item.icon} size={14} className="shrink-0" />
              <span>{item.label}</span>
            </>
          </NavLink>
        ))}
      </nav>

      <InstrumentSearch
        className="tradely-nav-search w-36 shrink-0 sm:w-48 lg:w-56"
        placeholder="Search ticker or name"
        clearOnSelect
        onSelect={openInstrument}
        inputClassName="h-8 bg-black"
      />
      </div>
    </header>
  );
}
