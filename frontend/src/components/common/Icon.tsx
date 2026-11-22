import type { SVGProps } from 'react';

export type IconName =
  | 'dashboard'
  | 'chart'
  | 'portfolio'
  | 'flask'
  | 'search'
  | 'refresh'
  | 'external'
  | 'plus'
  | 'trash'
  | 'info'
  | 'alert'
  | 'check'
  | 'close'
  | 'chevronLeft'
  | 'chevronRight'
  | 'news';

const paths: Record<IconName, string> = {
  dashboard:
    'M4 4h6v6H4V4Zm10 0h6v10h-6V4ZM4 14h6v6H4v-6Zm10 4h6v2h-6v-2Z',
  chart: 'M4 20V4m0 16h16M8 16v-5m4 5V7m4 9v-3m4 3V9',
  portfolio:
    'M4 8h16v11H4V8Zm4 0V6a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M4 12h16',
  flask: 'M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3M7.5 14h9',
  search: 'M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm4.5-2.5L21 21',
  refresh: 'M20 11a8 8 0 0 0-14.9-3M4 13a8 8 0 0 0 14.9 3M4 4v4h4m12 12v-4h-4',
  external: 'M14 4h6v6m0-6-8 8M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5',
  plus: 'M12 5v14M5 12h14',
  trash: 'M4 7h16M9 7V5h6v2m-8 0 1 13h8l1-13M10 11v6m4-6v6',
  info: 'M12 11v6m0-10h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z',
  alert: 'M12 9v4m0 4h.01M10.3 3.9 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z',
  check: 'M5 13l4 4L19 7',
  close: 'M6 6l12 12M18 6 6 18',
  chevronLeft: 'm15 18-6-6 6-6',
  chevronRight: 'm9 18 6-6-6-6',
  news: 'M4 4h14a2 2 0 0 1 2 2v13H6a2 2 0 0 1-2-2V4Zm0 0v13a2 2 0 0 0 2 2m3-11h7m-7 4h7m-7 4h4',
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
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      {...rest}
    >
      <path d={paths[name]} />
    </svg>
  );
}
