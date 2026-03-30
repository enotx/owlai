import { NextRequest, NextResponse } from "next/server";

const BACKEND_BASE_URL =
  process.env.INTERNAL_BACKEND_URL || "http://127.0.0.1:8000";

async function proxy(request: NextRequest, path: string[]) {
  const targetUrl = new URL(
    `/api/${path.join("/")}${request.nextUrl.search}`,
    BACKEND_BASE_URL
  );

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");

  const method = request.method;
  const hasBody = !["GET", "HEAD"].includes(method);

  const fetchOptions: Record<string, unknown> = {
    method,
    headers,
    body: hasBody ? request.body : undefined,
    redirect: "manual",
  };
  if (hasBody) {
    fetchOptions.duplex = "half";
  }

  const upstreamResponse = await fetch(
    targetUrl.toString(),
    fetchOptions as RequestInit
  );

  const responseHeaders = new Headers(upstreamResponse.headers);
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("content-length");

  return new NextResponse(upstreamResponse.body, {
    status: upstreamResponse.status,
    headers: responseHeaders,
  });
}

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

export async function GET(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function POST(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function OPTIONS(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, path);
}