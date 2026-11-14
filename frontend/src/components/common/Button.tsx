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
    'bg-terminal-accent text-white border border-terminal-accent hover:brightness-110 disabled:opacity-60',
  secondary:
    'bg-terminal-panelAlt text-terminal-text border border-terminal-border hover:border-[#343943] hover:text-white disabled:opacity-60',
  ghost:
    'bg-transparent text-terminal-muted border border-transparent hover:text-terminal-text hover:bg-white/[0.05] disabled:opacity-60',
  danger:
    'bg-transparent text-terminal-red border border-[#3f2528] hover:bg-[#221416] hover:border-[#5a3136] disabled:opacity-60',
};

const sizes: Record<Size, string> = {
  sm: 'h-7 px-2 text-2xs gap-1',
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
        'inline-flex items-center justify-center rounded-sm font-medium transition-colors',
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <span
          className="h-3 w-3 animate-spin rounded-full border border-current border-t-transparent"
          aria-hidden="true"
        />
      ) : icon ? (
        <Icon name={icon} size={size === 'sm' ? 12 : 14} />
      ) : null}
      {children}
    </button>
  );
}
