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

// ===== Streaming Chat (SSE) =====
/**
 * 流式对话：通过 SSE 逐 token 接收 AI 回复
 * 请求走 /api/chat/stream（Next.js Route Handler 代理，无跨域）
 */
export async function streamChat(
  taskId: string,
  message: string,
  onToken: (token: string) => void,
  onDone: (step: Record<string, unknown>) => void,
  onError: (error: string) => void,
) {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId, message }),
  });
  if (!res.ok || !res.body) {
    onError(`HTTP ${res.status}: ${res.statusText}`);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE 协议：事件以 \n\n 分隔
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      for (const line of part.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.token) onToken(data.token);
            if (data.done) onDone(data.step);
            if (data.error) onError(data.error);
          } catch {
            // JSON 解析失败忽略
          }
        }
      }
    }
  }
}


export default api;