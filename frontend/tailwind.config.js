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
          border: '#202328',
          borderSoft: '#15171a',
          text: '#e4e6e9',
          muted: '#858b94',
          accent: '#2f6feb',
          accentSoft: 'rgba(47,111,235,0.12)',
          green: '#24a889',
          red: '#e45b63',
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
