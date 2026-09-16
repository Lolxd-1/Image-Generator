// tailwind.config.ts — design tokens for the dark, dense, commercial-grade admin UI.
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        base: {
          950: "#0a0b0d",
          900: "#111318",
          800: "#181b22",
          700: "#22262f",
          600: "#2c3140",
          500: "#3a4152",
          400: "#5b6478",
          300: "#8890a0",
          200: "#b4bac6",
          100: "#dde0e6",
        },
        accent: {
          600: "#3d5afe",
          500: "#5b73ff",
          400: "#7c8fff",
        },
        danger: {
          600: "#dc2626",
          500: "#ef4444",
          400: "#f87171",
        },
        warn: {
          600: "#d97706",
          500: "#f59e0b",
          400: "#fbbf24",
        },
        ok: {
          600: "#16a34a",
          500: "#22c55e",
          400: "#4ade80",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      spacing: {
        4.5: "1.125rem",
      },
      borderRadius: {
        sm: "4px",
        md: "6px",
        lg: "10px",
      },
      boxShadow: {
        pop: "0 8px 24px -8px rgba(0,0,0,0.5)",
      },
    },
  },
  plugins: [],
} satisfies Config;
