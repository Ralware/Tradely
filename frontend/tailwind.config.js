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
          border: '#1e1e1e',
          borderSoft: '#161616',
          text: '#e8e8e8',
          muted: '#6b7280',
          accent: '#2f6feb',
          accentSoft: 'rgba(47,111,235,0.12)',
          green: '#26a69a',
          red: '#ef5350',
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
        'analysis-progress': {
          '0%': { transform: 'translateX(-110%)' },
          '100%': { transform: 'translateX(410%)' },
        },
        'panel-in': {
          '0%': { opacity: '0', transform: 'translateY(2px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'analysis-progress': 'analysis-progress 1.1s ease-in-out infinite',
        'panel-in': 'panel-in 240ms ease-out',
      },
    },
  },
  plugins: [],
};
