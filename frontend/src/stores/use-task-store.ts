// frontend/src/stores/use-task-store.ts

/**
 * Zustand 全局状态管理：Task、Knowledge、Chat
 * 支持 ReAct Agent 的多种 Step 类型
 */
import { create } from "zustand";

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

export type StepType = "user_message" | "assistant_message" | "tool_use";

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
 * 正在执行的代码块（tool_start → tool_result 之间的状态）
 */
/** 捕获的 DataFrame 元信息 */
export interface CapturedDataFrame {
  name: string;
  row_count: number;
  preview_count: number;
  columns: string[];
  capture_id: string;
}
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

interface TaskStore {
  // Task 状态
  tasks: Task[];
  currentTaskId: string | null;
  setTasks: (tasks: Task[]) => void;
  setCurrentTaskId: (id: string | null) => void;
  addTask: (task: Task) => void;
  removeTask: (id: string) => void;

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

  // 代码执行状态
  pendingTool: PendingToolExecution | null;
  setPendingTool: (tool: PendingToolExecution | null) => void;
  updatePendingToolResult: (result: PendingToolExecution["result"]) => void;

  // 数据面板展示
  previewData: Record<string, unknown>[] | null;
  previewColumns: string[];
  /** 当前预览来源标识，用于 DataPanel 标题展示 */
  previewSource: { type: "knowledge"; name: string } | { type: "step"; stepId: string; dfName: string } | null;
  setPreviewData: (data: Record<string, unknown>[] | null, columns?: string[], source?: TaskStore["previewSource"]) => void;
  /** 加载某个 Step 中捕获的 DataFrame 到数据面板 */
  loadStepDataframe: (stepId: string, dfName: string) => Promise<void>;

  // 加载状态
  isSending: boolean;
  setIsSending: (v: boolean) => void;
}

export const useTaskStore = create<TaskStore>((set) => ({
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
      pendingTool: null,
      isSending: false,
      knowledgeList: [],
      previewData: null,
      previewColumns: [],
      previewSource: null,
    }),

  addTask: (task) => set((s) => ({ tasks: [task, ...s.tasks] })),
  removeTask: (id) =>
    set((s) => ({
      tasks: s.tasks.filter((t) => t.id !== id),
      currentTaskId: s.currentTaskId === id ? null : s.currentTaskId,
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
  pendingTool: null,
  setPendingTool: (tool) => set({ pendingTool: tool }),
  updatePendingToolResult: (result) =>
    set((s) => {
      if (!s.pendingTool) return s;
      return {
        pendingTool: { ...s.pendingTool, status: "done", result },
      };
    }),

  // Data Panel
  previewData: null,
  previewColumns: [],
  previewSource: null,
  setPreviewData: (data, columns = [], source = null) =>
    set({ previewData: data, previewColumns: columns, previewSource: source }),
  loadStepDataframe: async (stepId, dfName) => {
    try {
      const { fetchStepDataframe } = await import("@/lib/api");
      const res = await fetchStepDataframe(stepId, dfName);
      const { columns, rows } = res.data;
      set({
        previewData: rows,
        previewColumns: columns,
        previewSource: { type: "step", stepId, dfName },
      });
    } catch (err) {
      console.error("Failed to load step dataframe:", err);
    }
  },

  // Loading
  isSending: false,
  setIsSending: (v) => set({ isSending: v }),
}));