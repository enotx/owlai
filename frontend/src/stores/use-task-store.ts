// frontend/src/stores/use-task-store.ts

/**
 * Zustand 全局状态管理：Task、Knowledge、Chat
 * 支持 ReAct Agent 的多种 Step 类型
 */
import { create } from "zustand";
import {AssetData} from "@/lib/api";

// ===== 类型定义 =====
export interface Task {
  id: string;
  title: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface Knowledge {
  id: string;
  task_id: string;
  type: string;
  name: string;
  file_path: string | null;
  metadata_json: string | null;
  created_at: string;
}

export type StepType =
  | "user_message"
  | "assistant_message"
  | "tool_use"
  | "visualization"
  | "hitl_request";


export interface Step {
  id: string;
  task_id: string;
  role: "user" | "assistant";
  step_type: StepType;
  content: string;
  code: string | null;
  code_output: string | null;
  created_at: string;
}

/**
 * 正在进行中的流式 assistant 回复（尚未持久化）
 * 用于在 UI 上实时显示 token 流
 */
export interface StreamingMessage {
  role: "assistant";
  step_type: "assistant_message";
  content: string;
}

/**
 * 捕获的 DataFrame 元信息
 */
export interface CapturedDataFrame {
  name: string;
  row_count: number;
  preview_count: number;
  columns: string[];
  capture_id: string;
}

/**
 * 正在执行的代码块（tool_start → tool_result 之间的状态）
 */
export interface PendingToolExecution {
  code: string;
  purpose: string;
  status: "running" | "done";
  result?: {
    success: boolean;
    output: string | null;
    error: string | null;
    time: number;
    dataframes?: CapturedDataFrame[];
  };
}

/**
 * SubTask 定义
 */
export interface SubTask {
  id: string;
  task_id: string;
  title: string;
  description: string | null;
  order: number;
  status: "pending" | "running" | "completed" | "failed";
  result: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * HITL 选项定义
 */
export interface HITLOption {
  label: string;
  value: string;
  badge?: string;
}
/**
 * HITL 请求数据
 */
export interface HITLRequest {
  title: string;
  description: string;
  options: HITLOption[];
  hitl_type?: "default" | "pipeline_confirmation" | "script_confirmation";
  pipeline?: PipelineProposal;
  script?: ScriptProposal;
}

export interface ScriptProposal {
  name: string;
  description: string;
  code: string;
  script_type: string;
  env_vars: Record<string, string>;
  allowed_modules: string[];
}

export interface PipelineProposal {
  table_name: string;
  display_name: string;
  description: string;
  source_type: string;
  source_config: Record<string, unknown>;
  transform_code: string;
  transform_description?: string;
  write_strategy: string;
  schema: Array<{ name: string; type: string }>;
  row_count: number;
  sample_rows: Record<string, unknown>[];
}

/**
 * 待确认的 Plan
 */
export interface PendingPlan {
  subtasks: Array<{
    title: string;
    description: string | null;
    order: number;
  }>;
  message: string; // PlanAgent的说明文本
}

/**
 * 数据预览来源信息（支持 Knowledge 和 Step DataFrame）
 */
export interface PreviewSource {
  type: "knowledge" | "step";
  name?: string;
  dfName?: string;
  stepId?: string;
  fileType?: "csv" | "excel" | "text";
  textContent?: string;
  availableSheets?: string[];
  currentSheet?: string;
  knowledgeId?: string;
}

interface TaskStore {
  // Task 状态
  tasks: Task[];
  currentTaskId: string | null;
  setTasks: (tasks: Task[]) => void;
  setCurrentTaskId: (id: string | null) => void;
  addTask: (task: Task) => void;
  removeTask: (id: string) => void;
  updateTaskTitle: (id: string, title: string) => void;

  // Knowledge 状态
  knowledgeList: Knowledge[];
  setKnowledgeList: (list: Knowledge[]) => void;
  addKnowledge: (item: Knowledge) => void;
  removeKnowledge: (id: string) => void;

  // Chat 状态 — 已持久化的 Steps
  steps: Step[];
  setSteps: (steps: Step[]) => void;
  addStep: (step: Step) => void;

  // 流式消息（未持久化的临时文本）
  streamingMessage: StreamingMessage | null;
  startStreaming: () => void;
  appendStreamingToken: (token: string) => void;
  clearStreaming: () => void;

  // 代码执行状态，按 taskId 存储 pendingTool
  pendingTools: Record<string, PendingToolExecution>;
  setPendingTool: (taskId: string, tool: PendingToolExecution | null) => void;
  updatePendingToolResult: (taskId: string, result: PendingToolExecution["result"]) => void;

  // 数据面板展示
  previewData: Record<string, unknown>[] | null;
  previewColumns: string[];
  previewSource: PreviewSource | null;
  setPreviewData: (
    data: Record<string, unknown>[] | null,
    columns?: string[],
    source?: PreviewSource | null
  ) => void;
  /** 加载某个 Step 中捕获的 DataFrame 到数据面板 */
  loadStepDataframe: (stepId: string, dfName: string) => Promise<void>;
  // 右侧 Data Panel 当前 Tab
  activeDataTab: "data" | "sources" | "assets";
  setActiveDataTab: (tab: "data" | "sources" | "assets") => void;


  // 加载状态
  isSending: boolean;
  setIsSending: (v: boolean) => void;

  // 等待LLM首次响应
  isWaitingResponse: boolean;
  setIsWaitingResponse: (v: boolean) => void;
  // 删除 step（及其后所有）
  removeStepsByIds: (ids: string[]) => void;

  // SubTask 状态
  subtasks: SubTask[];
  setSubTasks: (subtasks: SubTask[]) => void;
  addSubTask: (subtask: SubTask) => void;
  updateSubTask: (id: string, updates: Partial<SubTask>) => void;

  // 当前模式和模型选择
  currentMode: "auto" | "plan" | "analyst";
  setCurrentMode: (mode: "auto" | "plan" | "analyst") => void;
  selectedModel: { providerId: string; modelId: string } | null;
  setSelectedModel: (model: { providerId: string; modelId: string } | null) => void;

  // Plan确认流程
  pendingPlan: PendingPlan | null;
  setPendingPlan: (plan: PendingPlan | null) => void;
  
  // HITL 流程
  pendingHITL: { stepId: string; data: HITLRequest } | null;
  setPendingHITL: (hitl: { stepId: string; data: HITLRequest } | null) => void;
  
  // 添加计算属性的 getter（可选，方便使用）
  getCurrentPendingTool: () => PendingToolExecution | null;

  // Asset 状态
  assets: AssetData[];
  setAssets: (assets: AssetData[]) => void;
  addAsset: (asset: AssetData) => void;
  removeAsset: (id: string) => void;

  // Context management
  contextTokens: number;
  contextLoading: boolean;
  needsCompact: boolean;
  setContextTokens: (tokens: number, needsCompact: boolean) => void;
  setContextLoading: (loading: boolean) => void;
  refreshContextSize: () => Promise<void>;

}

export const useTaskStore = create<TaskStore>((set, get) => ({
  // Task
  tasks: [],
  currentTaskId: null,
  setTasks: (tasks) => set({ tasks }),
  // 切换 Task 时重置相关状态，避免数据混乱
  setCurrentTaskId: (id) =>
    set({
      currentTaskId: id,
      steps: [],
      streamingMessage: null,
      // pendingTool: null, // 不直接重置 pendingTool，保留不同 Task 的执行状态
      isSending: false,
      isWaitingResponse: false,
      knowledgeList: [],
      previewData: null,
      previewColumns: [],
      previewSource: null,
      subtasks: [], // 重置SubTask
      pendingPlan: null, // 重置待确认Plan
      pendingHITL: null, // 重置HITL
      currentMode: "auto", // 重置为默认模式
    }),

  addTask: (task) => set((s) => ({ tasks: [task, ...s.tasks] })),
  removeTask: (id) =>
    set((s) => ({
      tasks: s.tasks.filter((t) => t.id !== id),
      currentTaskId: s.currentTaskId === id ? null : s.currentTaskId,
    })),
  updateTaskTitle: (id, title) =>
    set((s) => ({
      tasks: s.tasks.map((t) => (t.id === id ? { ...t, title } : t)),
    })),

  // Knowledge
  knowledgeList: [],
  setKnowledgeList: (list) => set({ knowledgeList: list }),
  addKnowledge: (item) => set((s) => ({ knowledgeList: [...s.knowledgeList, item] })),
  removeKnowledge: (id) =>
    set((s) => ({ knowledgeList: s.knowledgeList.filter((k) => k.id !== id) })),

  // Chat — 已持久化的 Steps
  steps: [],
  setSteps: (steps) => set({ steps }),
  addStep: (step) => set((s) => ({ steps: [...s.steps, step] })),

  // 流式消息
  streamingMessage: null,
  startStreaming: () =>
    set({
      streamingMessage: {
        role: "assistant",
        step_type: "assistant_message",
        content: "",
      },
    }),
  appendStreamingToken: (token) =>
    set((s) => {
      if (!s.streamingMessage) return s;
      return {
        streamingMessage: {
          ...s.streamingMessage,
          content: s.streamingMessage.content + token,
        },
      };
    }),
  clearStreaming: () => set({ streamingMessage: null }),

  // 代码执行
  pendingTools: {},
  setPendingTool: (taskId, tool) =>
    set((s) => {
      const newTools = { ...s.pendingTools };
      if (tool === null) {
        delete newTools[taskId];
      } else {
        newTools[taskId] = tool;
      }
      return { pendingTools: newTools };
    }),
  updatePendingToolResult: (taskId, result) =>
    set((s) => {
      const tool = s.pendingTools[taskId];
      if (!tool) return s;
      return {
        pendingTools: {
          ...s.pendingTools,
          [taskId]: { ...tool, status: "done", result },
        },
      };
    }),
  getCurrentPendingTool: () => {
    const { currentTaskId, pendingTools } = get();
    return currentTaskId ? pendingTools[currentTaskId] ?? null : null;
  },


  // Data Panel
  previewData: null,
  previewColumns: [],
  previewSource: null,
  setPreviewData: (data, columns = [], source = null) =>
    set({ previewData: data, previewColumns: columns, previewSource: source, activeDataTab: "data" }),
  loadStepDataframe: async (stepId, dfName) => {
    try {
      const { fetchStepDataframe } = await import("@/lib/api");
      const res = await fetchStepDataframe(stepId, dfName);
      const { columns, rows } = res.data;
      set({
        previewData: rows,
        previewColumns: columns,
        previewSource: { type: "step", stepId, dfName },
        activeDataTab: "data",
      });
    } catch (err) {
      console.error("Failed to load step dataframe:", err);
    }
  },

  // Loading
  isSending: false,
  setIsSending: (v) => set({ isSending: v }),

  isWaitingResponse: false,
  setIsWaitingResponse: (v) => set({ isWaitingResponse: v }),
  removeStepsByIds: (ids: string[]) =>
    set((s) => {
      const idSet = new Set(ids);
      return { steps: s.steps.filter((st) => !idSet.has(st.id)) };
    }),


  // SubTask
  subtasks: [],
  setSubTasks: (subtasks) => set({ subtasks }),
  addSubTask: (subtask) => set((s) => ({ subtasks: [...s.subtasks, subtask] })),
  updateSubTask: (id, updates) =>
    set((s) => ({
      subtasks: s.subtasks.map((st) => (st.id === id ? { ...st, ...updates } : st)),
    })),

  // Mode & Model
  currentMode: "auto",
  setCurrentMode: (mode) => set({ currentMode: mode }),
  selectedModel: null,
  setSelectedModel: (model) => set({ selectedModel: model }),

  // Pending Plan
  pendingPlan: null,
  setPendingPlan: (plan) => set({ pendingPlan: plan }),

  // HITL
  pendingHITL: null,
  setPendingHITL: (hitl) => set({ pendingHITL: hitl }),

  // Data Panel Tab
  activeDataTab: "data",
  setActiveDataTab: (tab) => set({ activeDataTab: tab }),

  // Asset
  assets: [],
  setAssets: (assets) => set({ assets }),
  addAsset: (asset) => set((s) => ({ assets: [...s.assets, asset] })),
  removeAsset: (id) =>
    set((s) => ({ assets: s.assets.filter((a) => a.id !== id) })),
  // Context management
  contextTokens: 0,
  contextLoading: false,
  needsCompact: false,
  
  setContextTokens: (tokens, needsCompact) => 
    set({ contextTokens: tokens, needsCompact }),
  
  setContextLoading: (loading) => set({ contextLoading: loading }),
  
  refreshContextSize: async () => {
    const { currentTaskId, currentMode } = get();
    if (!currentTaskId) return;
    
    set({ contextLoading: true });
    try {
      const { fetchContextSize } = await import("@/lib/api");
      const res = await fetchContextSize(currentTaskId, currentMode);
      set({ 
        contextTokens: res.data.total_tokens,
        needsCompact: res.data.needs_compact,
      });
    } catch (err) {
      console.error("Failed to fetch context size:", err);
    } finally {
      set({ contextLoading: false });
    }
  },
}));