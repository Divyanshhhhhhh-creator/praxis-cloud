import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle (.next/standalone) for lean Cloud Run images
  output: "standalone",
  poweredByHeader: false,
};

export default nextConfig;
