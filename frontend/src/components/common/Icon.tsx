import type { ReactNode, SVGProps } from 'react';

export type IconName =
  | 'dashboard'
  | 'list'
  | 'chart'
  | 'portfolio'
  | 'flask'
  | 'search'
  | 'refresh'
  | 'external'
  | 'plus'
  | 'minus'
  | 'trash'
  | 'info'
  | 'alert'
  | 'check'
  | 'close'
  | 'chevronLeft'
  | 'chevronRight'
  | 'chevronDown'
  | 'chevronUp'
  | 'sort'
  | 'more'
  | 'calendar'
  | 'trendingUp'
  | 'link'
  | 'news';

const icons: Record<IconName, ReactNode> = {
  dashboard: <path d="M4 4h6v6H4V4Zm10 0h6v6h-6V4ZM4 14h6v6H4v-6Zm10 0h6v6h-6v-6Z" />,
  list: (
    <path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z" />
  ),
  chart: (
    <>
      <path d="M13 17V9" />
      <path d="M18 17V5" />
      <path d="M3 3v16a2 2 0 0 0 2 2h16" />
      <path d="M8 17v-3" />
    </>
  ),
  portfolio: (
    <>
      <path d="M12 12h.01" />
      <path d="M16 6V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2" />
      <path d="M22 13a18.15 18.15 0 0 1-20 0" />
      <rect width="20" height="14" x="2" y="6" rx="2" />
    </>
  ),
  flask: (
    <>
      <path d="M14 2v6a2 2 0 0 0 .245.96l5.51 10.08A2 2 0 0 1 18 22H6a2 2 0 0 1-1.755-2.96l5.51-10.08A2 2 0 0 0 10 8V2" />
      <path d="M6.453 15h11.094" />
      <path d="M8.5 2h7" />
    </>
  ),
  search: <path d="M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm4.5-2.5L21 21" />,
  refresh: (
    <>
      <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
      <path d="M21 3v5h-5" />
      <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
      <path d="M8 16H3v5" />
    </>
  ),
  external: (
    <path d="M14 4h6v6m0-6-8 8M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" />
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  minus: <path d="M5 12h14" />,
  trash: (
    <path d="M4 7h16M9 7V5h6v2m-8 0 1 13h8l1-13M10 11v6m4-6v6" />
  ),
  info: <path d="M12 11v6m0-10h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z" />,
  alert: (
    <path d="M12 9v4m0 4h.01M10.3 3.9 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
  ),
  check: <path d="M5 13l4 4L19 7" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  chevronLeft: <path d="m15 18-6-6 6-6" />,
  chevronRight: <path d="m9 18 6-6-6-6" />,
  chevronDown: <path d="m6 9 6 6 6-6" />,
  chevronUp: <path d="m18 15-6-6-6 6" />,
  sort: <path d="M8 9l4-4 4 4M8 15l4 4 4-4" />,
  more: <path d="M5 12h.01M12 12h.01M19 12h.01" />,
  calendar: <path d="M4 6h16v14H4V6Zm0 4h16M8 3v4m8-4v4" />,
  trendingUp: <path d="M3 17l6-6 4 4 7-7M21 8v5h-5" />,
  link: (
    <path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" />
  ),
  news: (
    <>
      <rect width="18" height="18" x="3" y="3" rx="2" />
      <path d="M7 8h8" />
      <path d="M7 12h10" />
      <path d="M7 16h6" />
    </>
  ),
};

export function Icon({
  name,
  size = 14,
  className,
  ...rest
}: {
  name: IconName;
  size?: number;
  className?: string;
} & SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      {...rest}
    >
      {icons[name]}
    </svg>
  );
}
