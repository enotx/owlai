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
    data_source_ids?: string[];
  }
) =>
  (await getApi()).post("/tasks", {
    title,
    description: options?.description,
    task_type: options?.task_type || "ad_hoc",
    asset_id: options?.asset_id,
    data_source_ids: options?.data_source_ids || [],
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
    data_source_ids?: string[];
  }
) => (await getApi()).put(`/tasks/${taskId}`, data);


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
  const globalTimeout = setTimeout(() => controller.abort(), 2 * 60 * 60 * 1000);

  try {
    const baseUrl = await getBaseUrl();
    const streamUrl = isTauriDesktop()
      ? `${baseUrl}/tasks/${taskId}/execute`
      : `/api/backend/tasks/${taskId}/execute`;

    const res = await fetch(streamUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options || {}),
      signal: controller.signal,
    });

    if (!res.ok || !res.body) {
      onEvent({ type: "error", content: `HTTP ${res.status}: ${res.statusText}` });
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
        onEvent({ type: "error", content: "Response stream timed out (no data for 90s)." });
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
        for (const line of part.split("\n")) {
          if (line.startsWith("data: ")) {
            try {
              const data: SSEEvent = JSON.parse(line.slice(6));
              onEvent(data);
            } catch { /* ignore */ }
          }
        }
      }
    }

    if (chunkTimer) clearTimeout(chunkTimer);
    if (buffer.trim()) {
      for (const line of buffer.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)));
          } catch { /* ignore */ }
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
 * 流式对话：通过 SSE 接收 Agent 的 ReAct 分析过程。
 * 使用回调分发不同事件类型。
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

  // 允许长任务（比如代码执行）最长 2 小时
  const globalTimeout = setTimeout(() => controller.abort(), 2 * 60 * 60 * 1000);
  
  try {
    const baseUrl = await getBaseUrl();
    // const streamUrl = `${baseUrl}/chat/stream`;
    // desktop 直连 FastAPI stream，dev/docker 走 Next 代理
    const streamUrl = isTauriDesktop()
      ? `${baseUrl}/chat/stream`
      : "/api/chat/stream";

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
      // 用户主动中止时静默处理，不推送 error 事件
      // 仅发送 done 让调用方知道流已结束
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
  (await getApi()).post<{ status: string; knowledge_id: string }>(
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
