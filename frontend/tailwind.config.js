/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        page: "#0b0c10",
        panel: {
          DEFAULT: "#131419",
          secondary: "#141519",
          inset: "#0e0f13",
        },
        border: {
          subtle: "#23252d",
          DEFAULT: "#1e2027",
          divider: "#262932",
        },
        text: {
          primary: "#f4f4f6",
          "primary-alt": "#e5e6ea",
          "primary-alt2": "#e9eaee",
          secondary: "#8b8f9c",
          "secondary-alt": "#6b7080",
          muted: "#5c6070",
          "muted-alt": "#4b4e58",
        },
        accent: {
          start: "#6366f1",
          end: "#4f46e5",
        },
        status: {
          amber: { DEFAULT: "#fbbf24", dark: "#f59e0b" },
          yellow: "#facc15",
          sky: { DEFAULT: "#7dd3fc", dark: "#38bdf8" },
          emerald: { DEFAULT: "#6ee7b7", dark: "#10b981" },
          rose: { DEFAULT: "#fda4af", dark: "#f43f5e" },
          violet: "#a78bfa",
          fuchsia: "#e879f9",
        },
      },
      fontFamily: {
        // Not yet wired to font-sans default — Inter isn't loaded in index.html.
        // Load the font and switch the default in the PR that adopts it.
        app: ["Inter", "sans-serif"],
      },
      borderRadius: {
        card: "10px",
        "card-lg": "13px",
      },
      boxShadow: {
        "page-frame": "0 40px 80px -20px rgba(0,0,0,0.6)",
        "cta-hover": "0 8px 20px -6px rgba(79,70,229,.55)",
        "focus-ring": "0 0 0 3px rgba(99,102,241,.15)",
      },
      backgroundImage: {
        "accent-gradient": "linear-gradient(135deg, #6366f1, #4f46e5)",
      },
    },
  },
  plugins: [],
};
