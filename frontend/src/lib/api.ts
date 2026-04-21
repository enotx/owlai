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
    "/api/backend";
    // process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";
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
export const createTask = async (
  title: string,
  options?: {
    description?: string;
    task_type?: "ad_hoc" | "script" | "pipeline" | "routine";
    asset_id?: string;
    pipeline_id?: string;
    data_source_ids?: string[];
    execution_backend?: string;
  }
) =>
  (await getApi()).post("/tasks", {
    title,
    description: options?.description,
    task_type: options?.task_type || "ad_hoc",
    asset_id: options?.asset_id,
    pipeline_id: options?.pipeline_id,
    data_source_ids: options?.data_source_ids || [],
    execution_backend: options?.execution_backend || "local",
  });

export const fetchTasks = async () => (await getApi()).get("/tasks");

export const deleteTask = async (taskId: string) =>
  (await getApi()).delete(`/tasks/${taskId}`);

export const renameTask = async (taskId: string, title: string) =>
  (await getApi()).put(`/tasks/${taskId}`, { title });

export const autoRenameTask = async (taskId: string) =>
  (await getApi()).post(`/tasks/${taskId}/auto-rename`);

export const updateTask = async (
  taskId: string,
  data: {
    title?: string;
    description?: string;
    task_type?: "ad_hoc" | "script" | "pipeline" | "routine";
    asset_id?: string | null;
    pipeline_id?: string | null;
    data_source_ids?: string[];
  }
) => (await getApi()).put(`/tasks/${taskId}`, data);

export interface StartExecutionResponse {
  task_id: string;
  execution_id: string;
  status: "running" | "completed" | "failed" | "cancelled";
  task_type: "script" | "pipeline" | "routine";
  reused: boolean;
}

export interface LatestExecutionInfo {
  execution_id: string;
  status: "running" | "completed" | "failed" | "cancelled";
  task_type: "script" | "pipeline" | "routine";
  created_at: number;
  updated_at: number;
  finished_at: number | null;
  error: string | null;
  last_seq: number;
}

export interface LatestExecutionResponse {
  task_id: string;
  execution: LatestExecutionInfo | null;
}

export const startTaskExecution = async (
  taskId: string,
  options?: {
    env_vars_override?: Record<string, string>;
    user_message?: string;
  }
) =>
  (await getApi()).post<StartExecutionResponse>(
    `/tasks/${taskId}/execute`,
    options || {}
  );

export const fetchLatestTaskExecution = async (taskId: string) =>
  (await getApi()).get<LatestExecutionResponse>(
    `/tasks/${taskId}/executions/latest`
  );

export const cancelTaskExecution = async (
  taskId: string,
  executionId: string,
) =>
  (await getApi()).post<{
    task_id: string;
    execution_id: string;
    status: string;
    cancelled: boolean;
    message?: string;
  }>(
    `/tasks/${taskId}/executions/${executionId}/cancel`
  );

export async function streamTaskExecutionEvents(
  taskId: string,
  executionId: string,
  onEvent: (event: SSEEvent) => void,
  options?: {
    afterSeq?: number;
    onSeq?: (seq: number) => void;
  },
  externalAbortController?: AbortController,
) {
  const controller = externalAbortController || new AbortController();
  const globalTimeout = setTimeout(() => controller.abort(), 2 * 60 * 60 * 1000);

  try {
    const baseUrl = await getBaseUrl();
    const afterSeq = options?.afterSeq ?? 0;
    const streamUrl = isTauriDesktop()
      ? `${baseUrl}/tasks/${taskId}/executions/${executionId}/events?after_seq=${afterSeq}`
      : `/api/backend/tasks/${taskId}/executions/${executionId}/events?after_seq=${afterSeq}`;

    const res = await fetch(streamUrl, {
      method: "GET",
      headers: { Accept: "text/event-stream" },
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
    let chunkTimer: ReturnType<typeof setTimeout> | null = null;

    const resetChunkTimer = () => {
      if (chunkTimer) clearTimeout(chunkTimer);
      chunkTimer = setTimeout(() => {
        reader.cancel();
        onEvent({
          type: "error",
          content: "Execution event stream timed out (no data for 90s).",
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

      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        let eventId: number | null = null;
        for (const line of part.split("\n")) {
          if (line.startsWith("id: ")) {
            const id = Number(line.slice(4).trim());
            if (!Number.isNaN(id)) {
              eventId = id;
            }
          }
          if (line.startsWith("data: ")) {
            try {
              const data: SSEEvent = JSON.parse(line.slice(6));
              onEvent(data);
            } catch {
              // ignore malformed event
            }
          }
        }
        if (eventId !== null) {
          options?.onSeq?.(eventId);
        }
      }

    }

    if (chunkTimer) clearTimeout(chunkTimer);

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
      onEvent({ type: "done", steps: [] });
    } else {
      throw err;
    }
  } finally {
    clearTimeout(globalTimeout);
  }
}

/**
 * 执行任务（script/pipeline/routine）
 * 返回 SSE stream，事件格式与 streamChat 相同
 */
export async function executeTask(
  taskId: string,
  onEvent: (event: SSEEvent) => void,
  options?: {
    env_vars_override?: Record<string, string>;
    user_message?: string;
  },
  externalAbortController?: AbortController,
) {
  const controller = externalAbortController || new AbortController();

  try {
    const startRes = await startTaskExecution(taskId, options);
    const { execution_id } = startRes.data;

    await streamTaskExecutionEvents(
      taskId,
      execution_id,
      onEvent,
      { afterSeq: 0 },
      controller,
    );
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      onEvent({ type: "done", steps: [] });
    } else {
      throw err;
    }
  }
}

// ===== Knowledge =====
export interface KnowledgeItem {
  id: string;
  task_id: string;
  type: string;
  name: string;
  file_path: string | null;
  metadata_json: string | null;
  created_at: string;
}

export const fetchKnowledge = async (taskId: string) =>
  (await getApi()).get<KnowledgeItem[]>("/knowledge", { params: { task_id: taskId } });

export const uploadKnowledge = async (taskId: string, file: File) => {
  const formData = new FormData();
  formData.append("task_id", taskId);
  formData.append("file", file);
  const baseURL = await getBaseUrl();
  
  // 根据文件大小动态计算超时时间
  const timeoutMs = Math.max(
    60_000,  // 最少 1 分钟
    Math.ceil(file.size / (1024 * 1024)) * 1_000  // 每 MB 给 1 秒
  );
  return axios.post(`${baseURL}/knowledge`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: timeoutMs,
    onUploadProgress: (progressEvent) => {
      // 可选：添加进度回调
      const percentCompleted = Math.round(
        (progressEvent.loaded * 100) / (progressEvent.total || 1)
      );
      console.log(`Upload progress: ${percentCompleted}%`);
    },
  });
};


export const deleteKnowledge = async (knowledgeId: string) =>
  (await getApi()).delete(`/knowledge/${knowledgeId}`);

export const addAssetToContext = async (taskId: string, assetId: string) =>
  (await getApi()).post<KnowledgeItem>("/knowledge/context/asset", {
    task_id: taskId,
    asset_id: assetId,
  });

export const addPipelineToContext = async (taskId: string, pipelineId: string) =>
  (await getApi()).post<KnowledgeItem>("/knowledge/context/pipeline", {
    task_id: taskId,
    pipeline_id: pipelineId,
  });

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
export const fetchStepDataframe = async (
  stepId: string,
  dfName: string,
  limit: number = 200
) =>
  (await getApi()).get<{
    columns: string[];
    rows: Record<string, unknown>[];
    total_rows: number;
    returned_rows: number;
    truncated: boolean;
  }>(
    `/chat/steps/${stepId}/dataframe/${dfName}`,
    { params: { limit } }
  );
  
// ===== Streaming Chat (SSE) =====
/**
 * 流式对话：通过 SSE 逐 token 接收 AI 回复
 * 请求走 /api/chat/stream（Next.js Route Handler 代理，无跨域）
 */
// ===== Streaming Chat (SSE) — ReAct Agent =====
export interface SSEEvent {
  // 新增 heartbeat：后端长耗时工具执行期间定期发，前端用于“续命”，UI可忽略
  type:
    | "text"
    | "tool_start"
    | "tool_result"
    | "visualization"
    | "step_saved"
    | "done"
    | "error"
    | "heartbeat"
    | "hitl_request";
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
  title?: string;
  chart_type?: string;
  option?: Record<string, unknown>;
  step?: Record<string, unknown>;
  steps?: Record<string, unknown>[];
  // HITL fields
  hitl_type?: string;
  hitl_title?: string;
  hitl_description?: string;
  hitl_options?: Array<{
    label: string;
    value: string;
    badge?: string;
  }>;
  // Script HITL fields
  script?: {
    name: string;
    description: string;
    code: string;
    script_type: string;
    env_vars: Record<string, string>;
    allowed_modules: string[];
  };
}

/**
 * 流式对话：两段式执行模型
 * 1. POST /chat/stream → 获取 execution_id
 * 2. GET /tasks/{task_id}/executions/{execution_id}/events → 消费事件流
 */
export async function streamChat(
  taskId: string,
  message: string,
  onEvent: (event: SSEEvent) => void,
  mode?: "auto" | "plan" | "analyst",
  modelOverride?: { provider_id: string; model_id: string },
  externalAbortController?: AbortController
) {
  const controller = externalAbortController || new AbortController();

  try {
    // Phase 1: 启动后台执行
    const api = await getApi();
    const body: Record<string, unknown> = {
      task_id: taskId,
      message,
    };
    if (mode) body.mode = mode;
    if (modelOverride) body.model_override = modelOverride;

    const startRes = await api.post<{
      task_id: string;
      execution_id: string;
      status: string;
      task_type: string;
      reused: boolean;
    }>("/chat/stream", body);

    const { execution_id } = startRes.data;

    // Phase 2: 消费事件流（复用已有的 streamTaskExecutionEvents）
    await streamTaskExecutionEvents(
      taskId,
      execution_id,
      onEvent,
      { afterSeq: 0 },
      controller,
    );
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      onEvent({ type: "done", steps: [] });
    } else {
      throw err;
    }
  }
}

/**
 * 启动 chat 后台执行（Phase 3 两段式第一步）
 */
export const startChatExecution = async (
  taskId: string,
  message: string,
  mode?: "auto" | "plan" | "analyst",
  modelOverride?: { provider_id: string; model_id: string },
) => {
  const api = await getApi();
  const body: Record<string, unknown> = {
    task_id: taskId,
    message,
  };
  if (mode) body.mode = mode;
  if (modelOverride) body.model_override = modelOverride;

  return api.post<{
    task_id: string;
    execution_id: string;
    status: string;
    task_type: string;
    reused: boolean;
  }>("/chat/stream", body);
};

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

// ===== File Download Helper =====
/**
 * 从 Content-Disposition 响应头中提取文件名
 */
function extractFilename(resp: Response, fallback: string): string {
  const disposition = resp.headers.get("content-disposition");
  if (disposition) {
    const utf8Match = disposition.match(/filename\*=UTF-8''(.+)/i);
    if (utf8Match) return decodeURIComponent(utf8Match[1]);
    const match = disposition.match(/filename="?([^";\n]+)"?/i);
    if (match) return match[1].trim();
  }
  return fallback;
}
/**
 * 通用文件下载
 * - Tauri: fetch → save dialog → writeFile
 * - Web:   fetch → Blob → <a> click
 */
async function downloadFile(url: string, defaultFilename: string): Promise<void> {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`Download failed: HTTP ${resp.status}`);
  }
  const filename = extractFilename(resp, defaultFilename);
  if (isTauriDesktop()) {
    const { save } = await import("@tauri-apps/plugin-dialog");
    const { writeFile } = await import("@tauri-apps/plugin-fs");
    const ext = filename.includes(".") ? filename.split(".").pop()! : "*";
    const filePath = await save({
      defaultPath: filename,
      filters: [{ name: filename, extensions: [ext] }],
    });
    if (!filePath) return; // 用户取消了保存
    const arrayBuffer = await resp.arrayBuffer();
    await writeFile(filePath, new Uint8Array(arrayBuffer));
  } else {
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(blobUrl);
      document.body.removeChild(a);
    }, 100);
  }
}
// ===== Data Export =====
/**
 * 下载 Knowledge 源文件
 */
export const downloadKnowledge = async (knowledgeId: string) => {
  const baseUrl = await getBaseUrl();
  const url = `${baseUrl}/knowledge/${knowledgeId}/download`;
  await downloadFile(url, `knowledge-${knowledgeId}`);
};
/**
 * 导出 DataFrame 为 Excel
 */
export const exportStepDataframe = async (stepId: string, dfName: string) => {
  const baseUrl = await getBaseUrl();
  const url = `${baseUrl}/chat/steps/${stepId}/dataframe/${dfName}/export`;
  await downloadFile(url, `${dfName}.xlsx`);
};
// ===== Chat Export =====
/**
 * 导出对话记录为 Markdown 或 Jupyter Notebook
 */
export const exportChat = async (
  taskId: string,
  format: "markdown" | "ipynb"
) => {
  const baseUrl = await getBaseUrl();
  const url = `${baseUrl}/tasks/${taskId}/export?format=${format}`;
  const ext = format === "markdown" ? "md" : "ipynb";
  await downloadFile(url, `chat-export.${ext}`);
};


// ===== Skills =====
export interface SkillData {
  id: string;
  name: string;
  description: string | null;
  prompt_markdown: string | null;
  reference_markdown: string | null;
  handler_type: string;
  handler_config: Record<string, unknown> | null;
  env_vars: Record<string, string>;
  allowed_modules: string[];
  is_active: boolean;
  is_system: boolean;
  slash_command: string | null;
  created_at: string;
  updated_at: string;
}

export const fetchSkills = async () =>
  (await getApi()).get<SkillData[]>("/skills");

export const createSkill = async (data: {
  name: string;
  description?: string;
  prompt_markdown?: string;
  reference_markdown?: string;
  handler_type?: string;
  handler_config?: Record<string, unknown>;
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
    reference_markdown?: string;
    handler_type?: string;
    handler_config?: Record<string, unknown>;
    env_vars?: Record<string, string>;
    allowed_modules?: string[];
    is_active?: boolean;
  }
) => (await getApi()).patch<SkillData>(`/skills/${id}`, data);

export const deleteSkill = async (id: string) =>
  (await getApi()).delete(`/skills/${id}`);

// ===== Visualizations =====
export interface VisualizationItem {
  id: string;
  task_id: string;
  subtask_id: string | null;
  step_id: string | null;
  title: string;
  chart_type: string;
  option_json: string;
  created_at: string;
  updated_at: string;
}

export const fetchVisualizations = async (taskId: string) =>
  (await getApi()).get<VisualizationItem[]>(`/visualizations/task/${taskId}`);

// ===== Step Management (Delete / Regenerate) =====
/**
 * 删除指定 Step 及其之后的所有 Step
 */
export const deleteStepAndAfter = async (stepId: string) =>
  (await getApi()).delete<{ deleted_ids: string[] }>(`/chat/steps/${stepId}`);
/**
 * 删除指定的单条 Step
 */
export const deleteStep = async (stepId: string) =>
  (await getApi()).delete<{ deleted_ids: string[] }>(`/chat/steps/${stepId}`);

/**
 * 重新生成：删除指定 Step 及其之后的所有 Step，返回需要重发的用户消息
 */
export const regenerateFromStep = async (stepId: string) =>
  (await getApi()).post<{
    user_message: string;
    task_id: string;
    deleted_ids: string[];
  }>(`/chat/steps/${stepId}/regenerate`);

// ===== Software Updates =====

export interface UpdateInfo {
  has_update: boolean;
  latest_version: string;
  current_version: string;
  release_notes?: string;
  download_url?: string;
  file_size?: number;
  file_name?: string;
  published_at?: string;
}

export interface PlatformInfo {
  platform: string;
  arch: string;
}

/**
 * 从 License Server 检查更新
 * 前端直接调用，不经过 Owl 后端
 */
export const checkForUpdate = async (
  currentVersion: string,
  platform: string,
  arch: string
): Promise<UpdateInfo> => {
  const response = await axios.get<UpdateInfo>(
    `${LICENSE_SERVER_URL}/v1/updates/check`,
    { params: { current_version: currentVersion, platform, arch } }
  );
  return response.data;
};

/**
 * 获取当前平台信息（非 Tauri 环境 fallback）
 */
export const getPlatformInfo = async (): Promise<PlatformInfo> => {
  const api = await getApi();
  const response = await api.get<PlatformInfo>("/updates/platform-info");
  return response.data;
};

/**
 * 触发后端安装已下载的更新包
 */
export const installUpdate = async (filePath: string) => {
  const api = await getApi();
  return api.post("/updates/install", { file_path: filePath });
};

// ===== DuckDB Warehouse =====
export interface DuckDBTableItem {
  id: string;
  table_name: string;
  display_name: string;
  description: string | null;
  table_schema_json: string;
  row_count: number;
  source_type: string;
  source_config: string | null;
  pipeline_id: string | null;
  data_updated_at: string | null;
  latest_data_date: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}
export const fetchDuckDBTables = async () =>
  (await getApi()).get<DuckDBTableItem[]>("/warehouse/tables");
export const previewDuckDBTable = async (
  tableId: string,
  limit: number = 50
) =>
  (await getApi()).get<{
    columns: string[];
    rows: Record<string, unknown>[];
    total_rows: number;
  }>(`/warehouse/tables/${tableId}/preview`, { params: { limit } });

export const deleteDuckDBTable = async (tableId: string) =>
  (await getApi()).delete(`/warehouse/tables/${tableId}`);

export const addTableToContext = async (tableId: string, taskId: string) =>
  (await getApi()).post<{
    status: string;
    knowledge_id: string;
    auto_added_pipeline_knowledge_id?: string | null;
  }>(
    `/warehouse/tables/${tableId}/add-to-context`,
    null,
    { params: { task_id: taskId } }
  );
export const removeTableFromContext = async (
  tableId: string,
  taskId: string
) =>
  (await getApi()).post(`/warehouse/tables/${tableId}/remove-from-context`, null, {
    params: { task_id: taskId },
  });

// ===== Assets =====
export interface AssetData {
  id: string;
  name: string;
  description: string | null;
  asset_type: "script" | "sop";
  source_task_id: string | null;
  code: string | null;
  script_type: "general" | "pipeline" | null;
  env_vars: Record<string, string>;
  allowed_modules: string[];
  content_markdown: string | null;
  created_at: string;
  updated_at: string;
}
export const fetchAssets = async (params?: {
  asset_type?: "script" | "sop";
  script_type?: "general" | "pipeline";
}) => {
  const query = new URLSearchParams();
  if (params?.asset_type) query.append("asset_type", params.asset_type);
  if (params?.script_type) query.append("script_type", params.script_type);
  return (await getApi()).get<AssetData[]>(`/assets?${query.toString()}`);
};
export const createAsset = async (data: {
  name: string;
  description?: string;
  asset_type: "script" | "sop";
  source_task_id?: string;
  code?: string;
  script_type?: "general" | "pipeline";
  env_vars?: Record<string, string>;
  allowed_modules?: string[];
  content_markdown?: string;
}) => (await getApi()).post<AssetData>("/assets", data);

export const updateAsset = async (
  assetId: string,
  data: {
    name?: string;
    description?: string;
    code?: string;
    env_vars?: Record<string, string>;
    allowed_modules?: string[];
    content_markdown?: string;
  }
) => (await getApi()).patch<AssetData>(`/assets/${assetId}`, data);

export const deleteAsset = async (assetId: string) =>
  (await getApi()).delete(`/assets/${assetId}`);

export const runAsset = async (
  assetId: string,
  data?: {
    user_message?: string;
    env_vars_override?: Record<string, string>;
  }
) =>
  (await getApi()).post<{ task_id: string; task_type: string }>(
    `/assets/${assetId}/run`,
    data || {}
  );

export interface DataPipelineData {
  id: string;
  name: string;
  description: string | null;
  source_task_id: string | null;
  source_type: string;
  source_config: string;
  transform_code: string;
  transform_description: string | null;
  target_table_name: string;
  write_strategy: string;
  upsert_key: string | null;
  output_schema: string | null;
  is_auto: boolean;
  freshness_policy_json: string;
  status: string;
  last_run_at: string | null;
  last_run_status: string | null;
  last_run_error: string | null;
  created_at: string;
  updated_at: string;
}

export const fetchDataPipelines = async () =>
  (await getApi()).get<DataPipelineData[]>("/data-pipelines");

// ===== Context Management =====
export interface ContextSizeResponse {
  total_tokens: number;
  system_tokens: number;
  history_tokens: number;
  compact_active: boolean;
  needs_compact: boolean;
  max_tokens: number;
}
export interface CompactContextResponse {
  success: boolean;
  original_tokens: number;
  compressed_tokens: number;
  compression_ratio: number;
  compact_anchor_step_id: string;
  compact_anchor_created_at: string;
  warning?: string;
}
export const fetchContextSize = async (taskId: string, mode: string = "analyst") =>
  (await getApi()).get<ContextSizeResponse>(`/chat/context-size`, {
    params: { task_id: taskId, mode },
  });

export interface CompactStatusResponse {
  status: "idle" | "running" | "completed" | "failed";
  progress: number;
  phase: string;
  message: string;
  result?: {
    success: boolean;
    original_tokens: number;
    compressed_tokens: number;
    compression_ratio: number;
    compact_anchor_step_id: string;
    compact_anchor_created_at: string;
    warning?: string;
  };
  error?: string;
}
export const startCompact = async (taskId: string) =>
  (await getApi()).post<{ status: string; task_id: string }>(
    `/chat/tasks/${taskId}/compact/start`
  );
export const getCompactStatus = async (taskId: string) =>
  (await getApi()).get<CompactStatusResponse>(
    `/chat/tasks/${taskId}/compact/status`
  );

  // ===== Runtimes (Jupyter) =====
export interface JupyterConfigData {
  id: string;
  name: string;
  server_url: string;
  token: string | null;
  kernel_name: string;
  security_level: string;
  data_transfer_mode: string;
  shared_storage_path: string | null;
  idle_timeout: number;
  status: string;
  last_connected_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface JupyterTestResult {
  success: boolean;
  message: string;
  kernel_specs: string[];
}

export interface SystemSettingData {
  key: string;
  value: string;
  updated_at: string;
}

export const fetchJupyterConfigs = async () =>
  (await getApi()).get<JupyterConfigData[]>("/runtimes");

export const createJupyterConfig = async (data: {
  name: string;
  server_url: string;
  token?: string;
  kernel_name?: string;
  security_level?: string;
  data_transfer_mode?: string;
  shared_storage_path?: string;
  idle_timeout?: number;
}) => (await getApi()).post<JupyterConfigData>("/runtimes", data);

export const updateJupyterConfig = async (
  id: string,
  data: Partial<{
    name: string;
    server_url: string;
    token: string;
    kernel_name: string;
    security_level: string;
    data_transfer_mode: string;
    shared_storage_path: string;
    idle_timeout: number;
  }>
) => (await getApi()).put<JupyterConfigData>(`/runtimes/${id}`, data);

export const deleteJupyterConfig = async (id: string) =>
  (await getApi()).delete(`/runtimes/${id}`);

export const testJupyterConnection = async (id: string) =>
  (await getApi()).post<JupyterTestResult>(`/runtimes/${id}/test`);

export const fetchDefaultRuntime = async () =>
  (await getApi()).get<SystemSettingData>("/runtimes/settings/default");

export const setDefaultRuntime = async (value: string) =>
  (await getApi()).put<SystemSettingData>("/runtimes/settings/default", { value });

export const switchTaskRuntime = async (taskId: string, executionBackend: string) =>
  (await getApi()).put<{
    ok: boolean;
    message: string;
    cleared: boolean;
    cleared_knowledge_count?: number;
  }>(`/tasks/${taskId}/runtime`, { execution_backend: executionBackend });