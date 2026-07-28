/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef4ff',
          100: '#dfe8ff',
          500: '#4a7bff',
          600: '#3f6ff0',
          700: '#315bd2',
          900: '#10213e',
        },
      },
      fontFamily: {
        sans: ['"InterVariable"', '"Inter"', '"SF Pro Text"', '"PingFang SC"', '"Microsoft YaHei"', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
