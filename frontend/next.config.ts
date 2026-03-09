// frontend/next.config.ts
// Next.js 配置文件

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export", // 核心：开启纯静态导出，生成 out 目录
  images: {
    unoptimized: true, // 静态导出必须关闭 Next.js 图片优化
  },
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