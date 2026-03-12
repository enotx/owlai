// frontend/src/lib/api.ts
/**
 * 统一 API 请求工具
 * - Web 开发模式：直连本地 FastAPI
 * - Tauri 桌面模式：通过 invoke 获取 sidecar 实际端口
 */
import axios, { type AxiosInstance } from "axios";

declare global {
  interface Window {
    __TAURI__?: unknown;
  }
}

let cachedBaseUrl: string | null = null;
let cachedApi: AxiosInstance | null = null;

/** 是否处于 Tauri 桌面环境 */
function isTauriDesktop(): boolean {
  return typeof window !== "undefined" && !!window.__TAURI__;
}

/** 获取后端 API Base URL */
export async function getBaseUrl(): Promise<string> {
  if (cachedBaseUrl) {
    return cachedBaseUrl;
  }

  // 桌面模式：从 Tauri 后端获取实际端口
  if (isTauriDesktop()) {
    const { invoke } = await import("@tauri-apps/api/core");
    const port = await invoke<number>("get_backend_port");
    cachedBaseUrl = `http://127.0.0.1:${port}/api`;
    return cachedBaseUrl;
  }

  // 浏览器 / 云端模式
  cachedBaseUrl =
    process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";
  return cachedBaseUrl;
}

/** 获取 Axios 实例（懒初始化） */
async function getApi(): Promise<AxiosInstance> {
  if (cachedApi) {
    return cachedApi;
  }

  const baseURL = await getBaseUrl();
  cachedApi = axios.create({
    baseURL,
    timeout: 30000,
    headers: { "Content-Type": "application/json" },
  });

  return cachedApi;
}

// ===== Health =====
export const checkHealth = async () => (await getApi()).get("/health");

// ===== Task =====
export const createTask = async (title: string, description?: string) =>
  (await getApi()).post("/tasks", { title, description });

export const fetchTasks = async () => (await getApi()).get("/tasks");

export const deleteTask = async (taskId: string) =>
  (await getApi()).delete(`/tasks/${taskId}`);

// ===== Knowledge =====
export const fetchKnowledge = async (taskId: string) =>
  (await getApi()).get("/knowledge", { params: { task_id: taskId } });

export const uploadKnowledge = async (taskId: string, file: File) => {
  const formData = new FormData();
  formData.append("task_id", taskId);
  formData.append("file", file);

  return (await getApi()).post("/knowledge", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const deleteKnowledge = async (knowledgeId: string) =>
  (await getApi()).delete(`/knowledge/${knowledgeId}`);

export const previewKnowledge = async (
  knowledgeId: string, 
  nRows: number = 50,
  sheetName?: string
) => {
  const params = new URLSearchParams({ n: nRows.toString() });
  if (sheetName) {
    params.append("sheet_name", sheetName);
  }
  return (await getApi()).get(`/knowledge/${knowledgeId}/preview?${params.toString()}`);
};


// ===== Chat =====
export const sendMessage = async (taskId: string, message: string) =>
  (await getApi()).post("/chat", { task_id: taskId, message });

export const fetchChatHistory = async (taskId: string) =>
  (await getApi()).get("/chat/history", { params: { task_id: taskId } });

// ===== Execute =====
export const executeCode = async (taskId: string, code: string) =>
  (await getApi()).post("/execute", { task_id: taskId, code });

// ===== Step DataFrame Preview =====
export const fetchStepDataframe = async (stepId: string, dfName: string) =>
  (await getApi()).get<{ columns: string[]; rows: Record<string, unknown>[] }>(
    `/chat/steps/${stepId}/dataframe/${dfName}`
  );

// ===== Streaming Chat (SSE) =====
/**
 * 流式对话：通过 SSE 逐 token 接收 AI 回复
 * 请求走 /api/chat/stream（Next.js Route Handler 代理，无跨域）
 */
// ===== Streaming Chat (SSE) — ReAct Agent =====
export interface SSEEvent {
  type: "text" | "tool_start" | "tool_result" | "step_saved" | "done" | "error";
  content?: string;
  code?: string;
  purpose?: string;
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
  step?: Record<string, unknown>;
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
  mode?: "auto" | "plan" | "analyst",
  modelOverride?: { provider_id: string; model_id: string }
) {
  const controller = new AbortController();
  const globalTimeout = setTimeout(() => controller.abort(), 5 * 60 * 1000);
  try {
    const baseUrl = await getBaseUrl();
    const streamUrl = `${baseUrl}/chat/stream`;
    const body: {
      task_id: string;
      message: string;
      mode?: string;
      model_override?: { provider_id: string; model_id: string };
    } = {
      task_id: taskId,
      message,
    };
    if (mode) {
      body.mode = mode;
    }
    if (modelOverride) {
      body.model_override = modelOverride;
    }
    const res = await fetch(streamUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
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
              // ignore
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
export const fetchProviders = async () => (await getApi()).get("/llm/providers");

export const createProvider = async (data: {
  display_name: string;
  base_url: string;
  api_key?: string;
  models: Array<{ id: string; name: string }>;
}) => (await getApi()).post("/llm/providers", data);

export const updateProvider = async (
  id: string,
  data: {
    display_name?: string;
    base_url?: string;
    api_key?: string;
    models?: Array<{ id: string; name: string }>;
  }
) => (await getApi()).patch(`/llm/providers/${id}`, data);

export const deleteProvider = async (id: string) =>
  (await getApi()).delete(`/llm/providers/${id}`);

export const testConnection = async (data: {
  base_url: string;
  api_key?: string;
}) => (await getApi()).post("/llm/providers/test-connection", data);

// ===== Agent Configs =====
export const fetchAgentConfigs = async () => (await getApi()).get("/llm/agents");

export const updateAgentConfig = async (
  agentType: string,
  data: { provider_id?: string; model_id?: string }
) => (await getApi()).patch(`/llm/agents/${agentType}`, data);

// ===== License Server APIs =====
const LICENSE_SERVER_URL = process.env.NEXT_PUBLIC_LICENSE_SERVER_URL || "https://owl-server.enotx.com/api";
export interface ActivationCodeRequest {
  code: string;
}
export interface LLMModelConfig {
  id: string;
  name: string;
}
export interface LLMProviderConfig {
  display_name: string;
  base_url: string;
  api_key?: string;
  models: LLMModelConfig[];
}
export interface AgentConfigData {
  agent_type: string;
  provider_id?: string;
  model_id?: string;
}
export interface DefaultConfig {
  providers: LLMProviderConfig[];
  agents: AgentConfigData[];
}
export interface ActivationCodeResponse {
  valid: boolean;
  message: string;
  config?: DefaultConfig;
}
export const verifyActivationCode = async (code: string): Promise<ActivationCodeResponse> => {
  const response = await axios.post<ActivationCodeResponse>(
    `${LICENSE_SERVER_URL}/activation/verify`,
    { code }
  );
  return response.data;
};
/**
 * 批量应用激活码配置到本地
 */
export const applyActivationConfig = async (config: DefaultConfig) => {
  const api = await getApi();
  
  // 1. 创建所有 Providers
  const providerIdMap = new Map<string, string>(); // display_name -> id
  
  for (const provider of config.providers) {
    const response = await api.post("/llm/providers", provider);
    providerIdMap.set(provider.display_name, response.data.id);
  }
  
  // 2. 更新 Agent 配置
  for (const agent of config.agents) {
    // 如果 agent 配置中有 provider_id，需要映射到实际创建的 provider id
    let actualProviderId = agent.provider_id;
    
    // 这里假设激活码配置中的 provider_id 是 display_name
    // 如果是实际 ID，则不需要映射
    if (actualProviderId && providerIdMap.has(actualProviderId)) {
      actualProviderId = providerIdMap.get(actualProviderId)!;
    }
    
    await api.patch(`/llm/agents/${agent.agent_type}`, {
      provider_id: actualProviderId,
      model_id: agent.model_id,
    });
  }
};

// ===== Database Management =====
export interface DBCompatibilityResponse {
  compatible: boolean;
  exists: boolean;
  issues: string[];
  db_path: string;
}
export interface DBRecreateResponse {
  success: boolean;
  message: string;
}
export const checkDatabaseCompatibility = async (): Promise<DBCompatibilityResponse> => {
  const response = await (await getApi()).get<DBCompatibilityResponse>("/database/compatibility");
  return response.data;
};
export const recreateDatabase = async (): Promise<DBRecreateResponse> => {
  const response = await (await getApi()).post<DBRecreateResponse>("/database/recreate");
  return response.data;
};


// ===== SubTask Management =====
export const fetchSubTasks = async (taskId: string) =>
  (await getApi()).get(`/subtasks/${taskId}`);

export const confirmPlan = async (
  taskId: string,
  data: {
    confirmed: boolean;
    subtasks?: Array<{
      task_id: string;
      title: string;
      description: string | null;
      order: number;
    }>;
    modifications?: string;
  }
) => (await getApi()).post(`/subtasks/${taskId}/confirm-plan`, data);

export const startSubTask = async (subtaskId: string) =>
  (await getApi()).post(`/subtasks/${subtaskId}/start`);

export const completeSubTask = async (
  subtaskId: string,
  resultSummary?: string
) =>
  (await getApi()).post(`/subtasks/${subtaskId}/complete`, null, {
    params: { result_summary: resultSummary },
  });

export const updateSubTask = async (
  subtaskId: string,
  data: {
    title?: string;
    description?: string;
    status?: "pending" | "running" | "completed" | "failed";
    result?: string;
  }
) => (await getApi()).patch(`/subtasks/${subtaskId}`, data);

// ===== Task Mode Management =====
export const updateTaskMode = async (
  taskId: string,
  mode: "auto" | "plan" | "analyst"
) => (await getApi()).patch(`/tasks/${taskId}/mode`, { mode });

// ===== Data Export =====
/**
 * 下载Knowledge源文件
 */
export const downloadKnowledge = async (knowledgeId: string) => {
  const baseUrl = await getBaseUrl();
  const url = `${baseUrl}/knowledge/${knowledgeId}/download`;
  window.open(url, '_blank');
};

/**
 * 导出DataFrame为Excel
 */
export const exportStepDataframe = async (stepId: string, dfName: string) => {
  const baseUrl = await getBaseUrl();
  const url = `${baseUrl}/chat/steps/${stepId}/dataframe/${dfName}/export`;
  window.open(url, '_blank');
};

// ===== Skills =====
export interface SkillData {
  id: string;
  name: string;
  description: string | null;
  prompt_markdown: string | null;
  env_vars: Record<string, string>;
  allowed_modules: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export const fetchSkills = async () =>
  (await getApi()).get<SkillData[]>("/skills");

export const createSkill = async (data: {
  name: string;
  description?: string;
  prompt_markdown?: string;
  env_vars?: Record<string, string>;
  allowed_modules?: string[];
  is_active?: boolean;
}) => (await getApi()).post<SkillData>("/skills", data);

export const updateSkill = async (
  id: string,
  data: {
    name?: string;
    description?: string;
    prompt_markdown?: string;
    env_vars?: Record<string, string>;
    allowed_modules?: string[];
    is_active?: boolean;
  }
) => (await getApi()).patch<SkillData>(`/skills/${id}`, data);

export const deleteSkill = async (id: string) =>
  (await getApi()).delete(`/skills/${id}`);