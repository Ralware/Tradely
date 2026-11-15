import type { ReactNode } from 'react';
import { cn } from '../../utils/format';

export type BadgeTone = 'neutral' | 'positive' | 'negative' | 'warning' | 'accent' | 'violet';

const tones: Record<BadgeTone, string> = {
  neutral: 'border-terminal-border text-terminal-muted bg-black',
  positive: 'border-[#1f4d43] text-terminal-green bg-black',
  negative: 'border-[#4d2424] text-terminal-red bg-black',
  warning: 'border-[#4d3d1f] text-terminal-amber bg-black',
  accent: 'border-[#254a8f] text-terminal-accent bg-black',
  violet: 'border-[#3f3560] text-terminal-violet bg-black',
};

interface BadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
  dot?: boolean;
  title?: string;
}

export function Badge({ tone = 'neutral', children, className, dot = false, title }: BadgeProps) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1 rounded-sm border px-1.5 text-2xs font-medium leading-4',
        tones[tone],
        className,
      )}
    >
      {dot ? <span className="h-1 w-1 rounded-full bg-current" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
