// frontend/next.config.ts
// Next.js 配置文件

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  images: {
    unoptimized: true,
  },
};
export default nextConfig;

  // API 代理转发：/api/* -> 后端 localhost:8000/api/*
  // 注意：纯静态导出后，Next.js 不再处理 API 路由，因此本段注释掉
  // async rewrites() {
  //   return [
  //     {
  //       source: "/api/:path*",
  //       destination: "http://localhost:8000/api/:path*",
  //     },
  //   ];
  // },
