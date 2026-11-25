/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: '#000000',
          panel: '#000000',
          panelAlt: '#000000',
          hover: '#111111',
          border: '#1d1d1d',
          borderSoft: '#111111',
          borderStrong: '#303030',
          text: '#f5f5f5',
          muted: '#929292',
          accent: '#268bff',
          accentSoft: 'rgba(38,139,255,0.14)',
          green: '#268bff',
          red: '#f04444',
          amber: '#f59e0b',
          violet: '#8f7ee7',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        panel: 'none',
      },
      fontSize: {
        '2xs': ['10px', '14px'],
      },
      keyframes: {
        'panel-in': {
          '0%': { opacity: '0', transform: 'translateY(2px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'panel-in': 'panel-in 240ms ease-out',
      },
    },
  },
  plugins: [],
};
