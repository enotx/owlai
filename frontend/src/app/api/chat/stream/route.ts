// frontend/src/app/api/chat/stream/route.ts

/**
 * Next.js Route Handler：代理后端 SSE 流式端点
 * 前端请求 /api/chat/stream → 本文件 → FastAPI /api/chat/stream
 * 直接透传 ReadableStream，无缓冲，无跨域问题
 */

const BACKEND = process.env.BACKEND_URL || "http://localhost:8000";

export async function POST(request: Request) {
  const body = await request.json();

  const upstream = await fetch(`${BACKEND}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(
      JSON.stringify({ error: `Backend error: ${upstream.status}` }),
      { status: upstream.status, headers: { "Content-Type": "application/json" } },
    );
  }

  // 透传 SSE 流，关键：不缓冲
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}