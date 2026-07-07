import type { Config } from "tailwindcss";

// Design tokens from UI/UX Pro Max — "Data-Dense Dashboard" system.
// Semantic colors + Fira type pairing + a refined shadow/radius scale.
const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Blue data + amber highlights (WCAG-adjusted).
        primary: {
          DEFAULT: "#1E40AF", // blue-800
          fg: "#FFFFFF",
          hover: "#1B3A9C",
        },
        secondary: "#3B82F6", // blue-500
        accent: "#D97706", // amber-600
        destructive: "#DC2626",
        canvas: "#F8FAFC",
        surface: "#FFFFFF",
        hairline: "#DBEAFE", // subtle blue-tinted border
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: {
        xl: "0.85rem",
        "2xl": "1.1rem",
      },
      boxShadow: {
        card: "0 1px 2px rgba(15, 23, 42, 0.04), 0 1px 3px rgba(15, 23, 42, 0.06)",
        "card-hover": "0 4px 12px rgba(15, 23, 42, 0.08)",
      },
    },
  },
  plugins: [],
};

export default config;
