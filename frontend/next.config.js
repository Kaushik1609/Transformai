/** @type {import('next').NextConfig} */
const nextConfig = {
  // Internal API URL used for SSR requests within the Docker network.
  // The public-facing API URL is set via NEXT_PUBLIC_API_URL.
  env: {
    INTERNAL_API_URL: process.env.INTERNAL_API_URL || "http://localhost:8000",
  },
  // Strict mode for highlighting potential issues in development.
  reactStrictMode: true,
};

module.exports = nextConfig;
