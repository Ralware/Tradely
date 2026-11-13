/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: '#0b0f16',
          panel: '#121821',
          panelAlt: '#0f1520',
          border: '#1f2a37',
          borderSoft: '#182230',
          text: '#e6edf6',
          muted: '#8b9bb0',
          accent: '#7c9cff',
          green: '#2fd18a',
          red: '#ff6b6b',
          amber: '#f0b95c',
          violet: '#c084fc',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: {
        panel: '0 1px 0 rgba(255,255,255,0.02), 0 12px 32px rgba(0,0,0,0.28)',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '-500px 0' },
          '100%': { backgroundPosition: '500px 0' },
        },
      },
      animation: {
        shimmer: 'shimmer 1.4s linear infinite',
      },
    },
  },
  plugins: [],
};
