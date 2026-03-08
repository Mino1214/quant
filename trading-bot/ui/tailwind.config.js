/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        long: '#22c55e',
        short: '#ef4444',
        wait: '#eab308',
        neutral: '#3b82f6',
        disabled: '#6b7280',
      },
    },
  },
  plugins: [],
}
