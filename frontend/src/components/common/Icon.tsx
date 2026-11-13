import type { SVGProps } from 'react';

export type IconName =
  | 'dashboard'
  | 'markets'
  | 'chart'
  | 'crypto'
  | 'portfolio'
  | 'flask'
  | 'settings'
  | 'search'
  | 'refresh'
  | 'external'
  | 'plus'
  | 'trash'
  | 'info'
  | 'alert'
  | 'check'
  | 'close'
  | 'menu'
  | 'arrowUp'
  | 'arrowDown';

const paths: Record<IconName, string> = {
  dashboard:
    'M4 4h6v6H4V4Zm10 0h6v10h-6V4ZM4 14h6v6H4v-6Zm10 4h6v2h-6v-2Z',
  markets:
    'M3 17l5-5 4 3 6-7 3 3v6H3v-0Zm2-12h14a1 1 0 0 1 1 1v1H4V6a1 1 0 0 1 1-1Z',
  chart: 'M4 20V4m0 16h16M8 16v-5m4 5V7m4 9v-3m4 3V9',
  crypto:
    'M12 3v2m0 14v2M8 7h5a2.5 2.5 0 0 1 0 5H8V7Zm0 5h6a2.5 2.5 0 0 1 0 5H8v-5Z',
  portfolio:
    'M4 8h16v11H4V8Zm4 0V6a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M4 12h16',
  flask: 'M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3M7.5 14h9',
  settings:
    'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8-3a8 8 0 0 0-.2-1.8l2-1.5-2-3.4-2.3 1a8 8 0 0 0-3.1-1.8L14 2h-4l-.4 2.5a8 8 0 0 0-3.1 1.8l-2.3-1-2 3.4 2 1.5a8 8 0 0 0 0 3.6l-2 1.5 2 3.4 2.3-1a8 8 0 0 0 3.1 1.8L10 22h4l.4-2.5a8 8 0 0 0 3.1-1.8l2.3 1 2-3.4-2-1.5A8 8 0 0 0 20 12Z',
  search: 'M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm4.5-2.5L21 21',
  refresh: 'M20 11a8 8 0 0 0-14.9-3M4 13a8 8 0 0 0 14.9 3M4 4v4h4m12 12v-4h-4',
  external: 'M14 4h6v6m0-6-8 8M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5',
  plus: 'M12 5v14M5 12h14',
  trash: 'M4 7h16M9 7V5h6v2m-8 0 1 13h8l1-13M10 11v6m4-6v6',
  info: 'M12 11v6m0-10h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z',
  alert: 'M12 9v4m0 4h.01M10.3 3.9 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z',
  check: 'M5 13l4 4L19 7',
  close: 'M6 6l12 12M18 6 6 18',
  menu: 'M4 7h16M4 12h16M4 17h16',
  arrowUp: 'M12 19V5m0 0-6 6m6-6 6 6',
  arrowDown: 'M12 5v14m0 0 6-6m-6 6-6-6',
};

interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 18, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      <path d={paths[name]} />
    </svg>
  );
}
