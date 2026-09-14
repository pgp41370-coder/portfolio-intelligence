import type { NextConfig } from "next";

// Browser requests to /api/v1/* are forwarded to the FastAPI backend, so the
// frontend never needs to know the backend's address or deal with CORS.
// Set API_BASE_URL at build time to use a deployed backend. In development it
// defaults to the local backend; without it in production, no API is connected.
const apiBaseUrl =
  process.env.API_BASE_URL ??
  (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : undefined);

const nextConfig: NextConfig = {
  async rewrites() {
    if (!apiBaseUrl) {
      return [];
    }
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiBaseUrl.replace(/\/$/, "")}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
