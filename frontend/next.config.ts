// frontend/next.config.ts
// Next.js 配置文件

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // API 代理转发：/api/* -> 后端 localhost:8000/api/*
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;