// frontend/src/stores/use-settings-store.ts

/**
 * Settings 状态管理：LLM Providers 配置
 */
import { create } from "zustand";

export interface LLMModel {
  id: string;
  name: string;
}

export interface LLMProvider {
  id: string;
  display_name: string;
  base_url: string;
  api_key: string | null;
  models: LLMModel[];
  created_at: string;
  updated_at: string;
}

interface SettingsStore {
  // Providers 列表
  providers: LLMProvider[];
  setProviders: (providers: LLMProvider[]) => void;
  addProvider: (provider: LLMProvider) => void;
  updateProvider: (id: string, provider: LLMProvider) => void;
  removeProvider: (id: string) => void;

  // 当前编辑的 Provider（null 表示新建）
  editingProvider: LLMProvider | null;
  setEditingProvider: (provider: LLMProvider | null) => void;

  // UI 状态
  isSettingsOpen: boolean;
  setSettingsOpen: (open: boolean) => void;
  
  currentView: "list" | "edit";
  setCurrentView: (view: "list" | "edit") => void;
}

export const useSettingsStore = create<SettingsStore>((set) => ({
  providers: [],
  setProviders: (providers) => set({ providers }),
  addProvider: (provider) =>
    set((s) => ({ providers: [...s.providers, provider] })),
  updateProvider: (id, provider) =>
    set((s) => ({
      providers: s.providers.map((p) => (p.id === id ? provider : p)),
    })),
  removeProvider: (id) =>
    set((s) => ({ providers: s.providers.filter((p) => p.id !== id) })),

  editingProvider: null,
  setEditingProvider: (provider) => set({ editingProvider: provider }),

  isSettingsOpen: false,
  setSettingsOpen: (open) => set({ isSettingsOpen: open }),

  currentView: "list",
  setCurrentView: (view) => set({ currentView: view }),
}));