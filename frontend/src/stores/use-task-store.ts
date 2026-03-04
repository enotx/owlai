// frontend/src/stores/use-task-store.ts

/**
 * Zustand 全局状态管理：Task、Knowledge、Chat
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

export interface Step {
  id: string;
  task_id: string;
  role: "user" | "assistant";
  content: string;
  code: string | null;
  code_output: string | null;
  created_at: string;
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

  // Chat 状态
  steps: Step[];
  setSteps: (steps: Step[]) => void;
  addStep: (step: Step) => void;

  /** 将 token 追加到最后一条 assistant 消息的 content */
  appendToLastStep: (token: string) => void;
  /** 流结束后用持久化数据替换临时 Step */
  finalizeLastStep: (step: Step) => void;

  // 数据面板展示
  previewData: Record<string, unknown>[] | null;
  previewColumns: string[];
  setPreviewData: (data: Record<string, unknown>[] | null, columns?: string[]) => void;

  // 加载状态
  isSending: boolean;
  setIsSending: (v: boolean) => void;
}

export const useTaskStore = create<TaskStore>((set) => ({
  // Task
  tasks: [],
  currentTaskId: null,
  setTasks: (tasks) => set({ tasks }),
  setCurrentTaskId: (id) => set({ currentTaskId: id }),
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

  // Chat
  steps: [],
  setSteps: (steps) => set({ steps }),
  addStep: (step) => set((s) => ({ steps: [...s.steps, step] })),

  appendToLastStep: (token) =>
    set((s) => {
      const steps = [...s.steps];
      const last = steps[steps.length - 1];
      if (last && last.role === "assistant") {
        steps[steps.length - 1] = { ...last, content: last.content + token };
      }
      return { steps };
    }),
  finalizeLastStep: (step) =>
    set((s) => {
      const steps = [...s.steps];
      const idx = steps.length - 1;
      if (idx >= 0 && steps[idx].role === "assistant") {
        steps[idx] = step;
      }
      return { steps };
    }),

  // Data Panel
  previewData: null,
  previewColumns: [],
  setPreviewData: (data, columns = []) => set({ previewData: data, previewColumns: columns }),

  // Loading
  isSending: false,
  setIsSending: (v) => set({ isSending: v }),
}));