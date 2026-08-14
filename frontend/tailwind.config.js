/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: { colors: { brand: { 50: "#effbfe", 100: "#d7f4fb", 500: "#00a6c8", 600: "#0085a3" } } } },
  plugins: [],
}
