// frontend/src/lib/api.ts

/**
 * 统一 API 请求工具
 * 所有请求走 /api/* ，由 Next.js rewrites 转发到后端，无 CORS 问题
 */
import axios from "axios";

const api = axios.create({
  baseURL: "/api",
  timeout: 30000,
  headers: { "Content-Type": "application/json" },
});

// ===== Health =====
export const checkHealth = () => api.get("/health");

// ===== Task =====
export const createTask = (title: string, description?: string) =>
  api.post("/tasks", { title, description });

export const fetchTasks = () => api.get("/tasks");

export const deleteTask = (taskId: string) => api.delete(`/tasks/${taskId}`);

// ===== Knowledge =====
export const fetchKnowledge = (taskId: string) =>
  api.get("/knowledge", { params: { task_id: taskId } });

export const uploadKnowledge = (taskId: string, file: File) => {
  const formData = new FormData();
  formData.append("task_id", taskId);
  formData.append("file", file);
  return api.post("/knowledge", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const deleteKnowledge = (knowledgeId: string) =>
  api.delete(`/knowledge/${knowledgeId}`);

// Knowledge Preview
export const previewKnowledge = (knowledgeId: string, n: number = 50) =>
  api.get(`/knowledge/${knowledgeId}/preview`, { params: { n } });


// ===== Chat =====
export const sendMessage = (taskId: string, message: string) =>
  api.post("/chat", { task_id: taskId, message });

export const fetchChatHistory = (taskId: string) =>
  api.get("/chat/history", { params: { task_id: taskId } });

// ===== Execute =====
export const executeCode = (taskId: string, code: string) =>
  api.post("/execute", { task_id: taskId, code });

// ===== Step DataFrame Preview =====
export const fetchStepDataframe = (stepId: string, dfName: string) =>
  api.get<{ columns: string[]; rows: Record<string, unknown>[] }>(
    `/chat/steps/${stepId}/dataframe/${dfName}`
  );


// ===== Streaming Chat (SSE) =====
/**
 * 流式对话：通过 SSE 逐 token 接收 AI 回复
 * 请求走 /api/chat/stream（Next.js Route Handler 代理，无跨域）
 */
// ===== Streaming Chat (SSE) — ReAct Agent =====
export interface SSEEvent {
  type:
    | "text"
    | "tool_start"
    | "tool_result"
    | "step_saved"
    | "done"
    | "error";
  // text
  content?: string;
  // tool_start
  code?: string;
  purpose?: string;
  // tool_result
  success?: boolean;
  output?: string | null;
  error?: string | null;
  time?: number;
  dataframes?: Array<{
    name: string;
    row_count: number;
    preview_count: number;
    columns: string[];
    capture_id: string;
  }>;
  // step_saved
  step?: Record<string, unknown>;
  // done
  steps?: Record<string, unknown>[];
}

/**
 * 流式对话：通过 SSE 接收 Agent 的 ReAct 分析过程。
 * 使用回调分发不同事件类型。
 */
export async function streamChat(
  taskId: string,
  message: string,
  onEvent: (event: SSEEvent) => void,
) {
  // 整体超时控制：5 分钟（覆盖多轮 tool 调用场景）
  const controller = new AbortController();
  const globalTimeout = setTimeout(() => controller.abort(), 5 * 60 * 1000);
  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId, message }),
      signal: controller.signal,
    });
    if (!res.ok || !res.body) {
      onEvent({
        type: "error",
        content: `HTTP ${res.status}: ${res.statusText}`,
      });
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    // 单 chunk 间隔超时：90 秒无数据视为异常
    let chunkTimer: ReturnType<typeof setTimeout> | null = null;
    const resetChunkTimer = () => {
      if (chunkTimer) clearTimeout(chunkTimer);
      chunkTimer = setTimeout(() => {
        reader.cancel();
        onEvent({
          type: "error",
          content: "Response stream timed out (no data for 90s).",
        });
        onEvent({ type: "done", steps: [] });
      }, 90_000);
    };
    resetChunkTimer();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      resetChunkTimer();
      buffer += decoder.decode(value, { stream: true });
      // SSE 协议：事件以 \n\n 分隔
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        for (const line of part.split("\n")) {
          if (line.startsWith("data: ")) {
            try {
              const data: SSEEvent = JSON.parse(line.slice(6));
              onEvent(data);
            } catch {
              // JSON 解析失败忽略
            }
          }
        }
      }
    }
    if (chunkTimer) clearTimeout(chunkTimer);
    // 处理 buffer 中可能残留的最后一个事件
    if (buffer.trim()) {
      for (const line of buffer.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            const data: SSEEvent = JSON.parse(line.slice(6));
            onEvent(data);
          } catch {
            // ignore
          }
        }
      }
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      onEvent({
        type: "error",
        content: "Request timed out (exceeded 5 minutes).",
      });
      onEvent({ type: "done", steps: [] });
    } else {
      throw err; // 让 message-input.tsx 的 catch 处理
    }
  } finally {
    clearTimeout(globalTimeout);
  }
}

// ===== LLM Providers =====
export const fetchProviders = () => api.get("/llm/providers");

export const createProvider = (data: {
  display_name: string;
  base_url: string;
  api_key?: string;
  models: Array<{ id: string; name: string }>;
}) => api.post("/llm/providers", data);

export const updateProvider = (
  id: string,
  data: {
    display_name?: string;
    base_url?: string;
    api_key?: string;
    models?: Array<{ id: string; name: string }>;
  }
) => api.patch(`/llm/providers/${id}`, data);

export const deleteProvider = (id: string) => api.delete(`/llm/providers/${id}`);

export const testConnection = (data: { base_url: string; api_key?: string }) =>
  api.post("/llm/providers/test-connection", data);

// ===== Agent Configs =====
export const fetchAgentConfigs = () => api.get("/llm/agents");
export const updateAgentConfig = (
  agentType: string,
  data: { provider_id?: string; model_id?: string }
) => api.patch(`/llm/agents/${agentType}`, data);

export default api;