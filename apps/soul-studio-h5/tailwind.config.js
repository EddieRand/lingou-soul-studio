/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        soul: {
          purple: '#8B5CF6',
          pink: '#EC4899', 
          blue: '#3B82F6',
          indigo: '#6366F1',
          cyan: '#06B6D4',
        },
        card: '#FAFAFF',
      },
      backgroundImage: {
        'soul-gradient': 'linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%)',
        'soul-gradient-soft': 'linear-gradient(135deg, #e0c3fc 0%, #8ec5fc 100%)',
        'glow-purple': 'radial-gradient(circle, rgba(139, 92, 246, 0.3) 0%, transparent 70%)',
      },
      boxShadow: {
        'soul': '0 4px 20px rgba(139, 92, 246, 0.25)',
        'soul-lg': '0 8px 40px rgba(139, 92, 246, 0.35)',
        'glow': '0 0 20px rgba(139, 92, 246, 0.5)',
      },
    },
  },
  plugins: [],
}