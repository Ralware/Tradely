import type { ReactNode } from 'react';
import { cn } from '../../utils/format';

export type BadgeTone = 'neutral' | 'positive' | 'negative' | 'warning' | 'accent' | 'violet';

const tones: Record<BadgeTone, string> = {
  neutral: 'border-terminal-border text-terminal-muted',
  positive: 'border-[#12382C] text-terminal-green',
  negative: 'border-[#3A1C20] text-terminal-red',
  warning: 'border-[#3A3018] text-terminal-amber',
  accent: 'border-[#163A66] text-terminal-accent',
  violet: 'border-[#2E2848] text-terminal-violet',
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
        'inline-flex items-center gap-1 rounded border px-1.5 text-2xs font-medium leading-4',
        tones[tone],
        className,
      )}
    >
      {dot ? <span className="h-1 w-1 rounded-full bg-current" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
