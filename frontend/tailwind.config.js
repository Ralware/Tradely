/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: 'var(--terminal-bg)',
          panel: 'var(--terminal-panel)',
          panelAlt: 'var(--terminal-panel-alt)',
          border: 'var(--terminal-border)',
          borderSoft: 'var(--terminal-border-soft)',
          text: 'var(--terminal-text)',
          muted: 'var(--terminal-muted)',
          accent: 'var(--terminal-accent)',
          accentSoft: 'var(--terminal-accent-soft)',
          hover: 'var(--terminal-hover)',
          activeBg: 'var(--terminal-active-bg)',
          green: 'var(--terminal-green)',
          red: 'var(--terminal-red)',
          amber: 'var(--terminal-amber)',
          violet: 'var(--terminal-violet)',
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