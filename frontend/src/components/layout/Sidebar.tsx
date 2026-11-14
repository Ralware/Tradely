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

const navigation: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: 'dashboard', end: true },
  { to: '/markets', label: 'Markets', icon: 'markets' },
  { to: '/stocks', label: 'Stock Analysis', icon: 'chart' },
  { to: '/crypto', label: 'Crypto Analysis', icon: 'crypto' },
  { to: '/portfolio', label: 'Portfolio', icon: 'portfolio' },
  { to: '/backtesting', label: 'Backtesting', icon: 'flask' },
  { to: '/settings', label: 'Settings', icon: 'settings' },
];

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col border-r border-terminal-border bg-terminal-panel">
      <div className="flex items-center gap-2 border-b border-terminal-border px-3 py-3">
        <span className="flex h-6 w-6 items-center justify-center rounded-sm bg-terminal-accent text-white">
          <Icon name="chart" size={14} />
        </span>
        <div className="min-w-0">
          <p className="text-xs font-semibold text-terminal-text">Tradely</p>
          <p className="text-2xs text-terminal-muted">Market Terminal</p>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2" aria-label="Main Navigation">
        {navigation.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2 rounded-sm px-2 py-1.5 text-xs font-medium transition-colors',
                isActive
                  ? 'bg-[#20242b] text-terminal-text'
                  : 'text-terminal-muted hover:bg-white/[0.04] hover:text-terminal-text',
              )
            }
          >
            {({ isActive }) => (
              <>
                <span className={isActive ? 'text-terminal-accent' : 'text-terminal-muted'}>
                  <Icon name={item.icon} size={14} />
                </span>
                <span className="truncate">{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-terminal-border px-3 py-2">
        <p className="text-2xs text-terminal-muted">Research Only · No Order Execution</p>
      </div>
    </div>
  );
}
