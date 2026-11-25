/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: '#000000',
          panel: '#080808',
          panelAlt: '#0D0D0D',
          surface: '#080808',
          surface2: '#0D0D0D',
          hover: '#141414',
          border: '#1C1C1C',
          borderSoft: '#141414',
          borderStrong: '#2A2A2A',
          text: '#F5F5F5',
          muted: '#929292',
          faint: '#626262',
          accent: '#1685FF',
          accentSoft: '#102033',
          green: '#00C78A',
          red: '#F04452',
          amber: '#C4A15A',
          violet: '#8F7EE7',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      borderRadius: {
        sm: '2px',
        DEFAULT: '4px',
        md: '4px',
        lg: '4px',
        xl: '4px',
        '2xl': '4px',
        '3xl': '4px',
      },
      boxShadow: {
        none: 'none',
        panel: 'none',
        sm: 'none',
        DEFAULT: 'none',
        md: 'none',
        lg: 'none',
        xl: 'none',
        '2xl': 'none',
      },
      fontSize: {
        '2xs': ['10px', '14px'],
      },
      keyframes: {
        'wave-flow': {
          '0%': { transform: 'translateX(-120%)' },
          '100%': { transform: 'translateX(280%)' },
        },
      },
      animation: {
        'wave-flow': 'wave-flow 1.15s linear infinite',
      },
    },
  },
  plugins: [],
};
