/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: '#0b0c0e',
          panel: '#121417',
          panelAlt: '#0e1012',
          border: '#24272e',
          borderSoft: '#1a1d22',
          text: '#e6e8eb',
          muted: '#8b909a',
          accent: '#2f6feb',
          accentSoft: '#16233a',
          green: '#26a69a',
          red: '#ef5350',
          amber: '#d6a45a',
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
    },
  },
  plugins: [],
};
