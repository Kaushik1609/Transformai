/** @type {import('tailwindcss').Config} */
const defaultTheme = require("tailwindcss/defaultTheme");
module.exports = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  prefix: "",
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      fontFamily: {
        sans: ["var(--font-geist-sans)", ...defaultTheme.fontFamily.sans],
        mono: ["var(--font-jetbrains-mono)", ...defaultTheme.fontFamily.mono],
      },
      colors: {
        border: "var(--border)",
        input: "var(--input)",
        ring: "var(--ring)",
        background: "var(--background)",
        foreground: "var(--foreground)",
        success: "var(--success)",
        warning: "var(--warning)",
        "surface-elevated": "var(--surface-elevated)",
        sidebar: {
          bg: "var(--sidebar-bg)",
          border: "var(--sidebar-border)",
        },
        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        "primary-container": "var(--primary-container)",
        "on-primary-container": "var(--on-primary-container)",
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        "secondary-container": "var(--secondary-container)",
        "on-secondary-container": "var(--on-secondary-container)",
        tertiary: "var(--tertiary)",
        "tertiary-foreground": "var(--tertiary-foreground)",
        "tertiary-container": "var(--tertiary-container)",
        "on-tertiary-container": "var(--on-tertiary-container)",
        destructive: {
          DEFAULT: "var(--destructive)",
          foreground: "var(--destructive-foreground)",
        },
        "error-container": "var(--error-container)",
        "on-error-container": "var(--on-error-container)",
        muted: {
          DEFAULT: "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-foreground)",
        },
        popover: {
          DEFAULT: "var(--popover)",
          foreground: "var(--popover-foreground)",
        },
        card: {
          DEFAULT: "var(--card)",
          foreground: "var(--card-foreground)",
        },
        outline: "var(--outline)",
        "outline-variant": "var(--outline-variant)",
        "surface-variant": "var(--surface-variant)",
        "on-surface-variant": "var(--on-surface-variant)",
        "surface-container-lowest": "var(--surface-container-lowest)",
        "surface-container-low": "var(--surface-container-low)",
        "surface-container": "var(--surface-container)",
        "surface-container-high": "var(--surface-container-high)",
        "surface-container-highest": "var(--surface-container-highest)",
        "output-summary": "var(--output-summary)",
        "output-linkedin": "var(--output-linkedin)",
        "output-advisory": "var(--output-advisory)",
        "output-presentation": "var(--output-presentation)",
        "output-x": "var(--output-x)",
        "output-infographic": "var(--output-infographic)",
        "output-video": "var(--output-video)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        fadeIn: {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "fade-in": "fadeIn 0.3s ease-out",
        shimmer: "shimmer 1.5s infinite",
      },
    },
  },
  plugins: [],
};