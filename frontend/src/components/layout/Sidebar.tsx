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
    <div className="flex h-full flex-col border-r border-terminal-border bg-terminal-panelAlt">
      <div className="flex items-center gap-2.5 border-b border-terminal-border px-4 py-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-[#33477a] bg-[#141d33] text-terminal-accent">
          <Icon name="chart" size={18} />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold tracking-tight text-terminal-text">Tradely</p>
          <p className="text-[10px] uppercase tracking-[0.12em] text-terminal-muted">
            Private · Local
          </p>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2" aria-label="Main navigation">
        {navigation.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-colors',
                isActive
                  ? 'bg-[#1b2740] text-terminal-text'
                  : 'text-terminal-muted hover:bg-white/[0.04] hover:text-terminal-text',
              )
            }
          >
            {({ isActive }) => (
              <>
                <span className={isActive ? 'text-terminal-accent' : 'text-terminal-muted'}>
                  <Icon name={item.icon} size={16} />
                </span>
                <span className="truncate">{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-terminal-border px-4 py-3">
        <p className="text-[10px] leading-relaxed text-terminal-muted">
          Rule-based research. No AI, no order execution, no paper trading.
        </p>
      </div>
    </div>
  );
}
