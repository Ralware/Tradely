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
    'bg-[#2b3f6b] text-white border border-[#40598f] hover:bg-[#334b7f] disabled:bg-[#243148]',
  secondary:
    'bg-terminal-panelAlt text-terminal-text border border-terminal-border hover:border-[#34445a] hover:bg-[#151d2a]',
  ghost:
    'bg-transparent text-terminal-muted border border-transparent hover:text-terminal-text hover:bg-white/5',
  danger:
    'bg-transparent text-terminal-red border border-[#4a2a33] hover:bg-[#2a1419] hover:border-[#6b3542]',
};

const sizes: Record<Size, string> = {
  sm: 'h-8 px-2.5 text-xs gap-1.5',
  md: 'h-10 px-3.5 text-sm gap-2',
};

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  icon,
  className,
  children,
  disabled,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        'inline-flex items-center justify-center rounded-lg font-medium transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-60',
        variants[variant],
        sizes[size],
        className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? (
        <span
          className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white"
          aria-hidden="true"
        />
      ) : icon ? (
        <Icon name={icon} size={size === 'sm' ? 14 : 16} />
      ) : null}
      {children}
    </button>
  );
}
