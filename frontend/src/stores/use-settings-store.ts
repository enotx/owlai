// frontend/src/stores/use-settings-store.ts

/**
 * Settings 状态管理：LLM Providers 配置
 */
import { create } from "zustand";
import type { SkillData } from "@/lib/api";


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

export interface AgentConfig {
  id: string;
  agent_type: string;
  provider_id: string | null;
  model_id: string | null;
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

  // Agent 配置
  agentConfigs: AgentConfig[];
  setAgentConfigs: (configs: AgentConfig[]) => void;
  updateLocalAgentConfig: (agentType: string, config: AgentConfig) => void;


  // 当前编辑的 Provider（null 表示新建）
  editingProvider: LLMProvider | null;
  setEditingProvider: (provider: LLMProvider | null) => void;

  // UI 状态
  isSettingsOpen: boolean;
  setSettingsOpen: (open: boolean) => void;
  
  currentView: "list" | "edit";
  setCurrentView: (view: "list" | "edit") => void;
  // 在 currentView 相关代码之后追加：

  // Skill 列表
  skills: SkillData[];
  setSkills: (skills: SkillData[]) => void;
  addSkill: (skill: SkillData) => void;
  updateSkillInStore: (id: string, skill: SkillData) => void;
  removeSkill: (id: string) => void;
  // 当前编辑的 Skill（null 表示新建）
  editingSkill: SkillData | null;
  setEditingSkill: (skill: SkillData | null) => void;
  // Skill 视图状态
  skillView: "list" | "edit";
  setSkillView: (view: "list" | "edit") => void;

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

  agentConfigs: [],
  setAgentConfigs: (configs) => set({ agentConfigs: configs }),
  updateLocalAgentConfig: (agentType, config) =>
    set((s) => ({
      agentConfigs: s.agentConfigs.map((c) =>
        c.agent_type === agentType ? config : c
      ),
    })),

  isSettingsOpen: false,
  setSettingsOpen: (open) => set({ isSettingsOpen: open }),

  currentView: "list",
  setCurrentView: (view) => set({ currentView: view }),

    // Skill 状态
  skills: [],
  setSkills: (skills) => set({ skills }),
  addSkill: (skill) => set((s) => ({ skills: [...s.skills, skill] })),
  updateSkillInStore: (id, skill) =>
    set((s) => ({
      skills: s.skills.map((sk) => (sk.id === id ? skill : sk)),
    })),
  removeSkill: (id) =>
    set((s) => ({ skills: s.skills.filter((sk) => sk.id !== id) })),
  editingSkill: null,
  setEditingSkill: (skill) => set({ editingSkill: skill }),
  skillView: "list",
  setSkillView: (view) => set({ skillView: view }),

}));