/** @type {import('next').NextConfig} */
const nextConfig = {
  // Internal API URL used for SSR requests within the Docker network.
  // The public-facing API URL is set via NEXT_PUBLIC_API_URL.
  env: {
    INTERNAL_API_URL: process.env.INTERNAL_API_URL || "http://localhost:8000",
  },
  // Standalone output for Docker production. Omitted on Vercel where Vercel manages serverless output.
  output: process.env.VERCEL ? undefined : "standalone",
  // Strict mode for highlighting potential issues in development.
  reactStrictMode: true,
  async rewrites() {
    const backendUrl =
      process.env.INTERNAL_API_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: "/health",
        destination: `${backendUrl}/health`,
      },
      {
        source: "/ready",
        destination: `${backendUrl}/ready`,
      },
    ];
  },
};

module.exports = nextConfig;
