import type { ReactNode } from 'react';
import { cn } from '../../utils/format';

export type BadgeTone = 'neutral' | 'positive' | 'negative' | 'warning' | 'accent' | 'violet';

const tones: Record<BadgeTone, string> = {
  neutral: 'border-terminal-border text-terminal-muted bg-white/[0.02]',
  positive: 'border-[#245c46] text-terminal-green bg-[#0f2a20]',
  negative: 'border-[#5c2a2a] text-terminal-red bg-[#2a1414]',
  warning: 'border-[#5c4a24] text-terminal-amber bg-[#2a2210]',
  accent: 'border-[#33477a] text-terminal-accent bg-[#141d33]',
  violet: 'border-[#4a3468] text-terminal-violet bg-[#1d142c]',
};

interface BadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
  dot?: boolean;
}

export function Badge({ tone = 'neutral', children, className, dot = false }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-5',
        tones[tone],
        className,
      )}
    >
      {dot ? <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
