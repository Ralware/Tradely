import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from '../../utils/format';
import { Icon } from './Icon';
import type { IconName } from './Icon';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'sm' | 'md';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: IconName;
  children?: ReactNode;
}

const variants: Record<Variant, string> = {
  primary:
    'bg-terminal-accent text-white border border-terminal-accent hover:bg-[#3A9BFF] disabled:opacity-60',
  secondary:
    'bg-terminal-panel text-terminal-text border border-terminal-border hover:bg-terminal-hover hover:border-terminal-borderStrong disabled:opacity-60',
  ghost:
    'bg-terminal-bg text-terminal-muted border border-transparent hover:text-terminal-text hover:bg-terminal-hover disabled:opacity-60',
  danger:
    'bg-terminal-bg text-terminal-red border border-[#3A1C20] hover:bg-[#1A0C0E] hover:border-[#5A3136] disabled:opacity-60',
};

const sizes: Record<Size, string> = {
  sm: 'h-7 px-2.5 text-2xs gap-1',
  md: 'h-8 px-3 text-xs gap-1.5',
};

export function Button({
  variant = 'secondary',
  size = 'sm',
  loading = false,
  icon,
  children,
  className,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center whitespace-nowrap rounded font-medium focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-terminal-accent disabled:cursor-not-allowed',
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <span className="skeleton-block inline-block h-3 w-3 shrink-0" aria-hidden="true" />
      ) : icon ? (
        <Icon name={icon} size={size === 'sm' ? 12 : 14} />
      ) : null}
      {children}
    </button>
  );
}
