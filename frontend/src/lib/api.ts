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

// ===== Chat =====
export const sendMessage = (taskId: string, message: string) =>
  api.post("/chat", { task_id: taskId, message });

export const fetchChatHistory = (taskId: string) =>
  api.get("/chat/history", { params: { task_id: taskId } });

// ===== Execute =====
export const executeCode = (taskId: string, code: string) =>
  api.post("/execute", { task_id: taskId, code });

export default api;