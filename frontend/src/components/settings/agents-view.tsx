// frontend/src/components/settings/agents-view.tsx
"use client";

import { useEffect, useState } from "react";
import { useSettingsStore } from "@/stores/use-settings-store";
import { fetchAgentConfigs, updateAgentConfig } from "@/lib/api";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const AGENT_LABELS: Record<string, { label: string; p_title?: string }> = {
  default: { label: "Default Agent" },
  plan: { label: "Plan Mode", p_title: "(Plato)" },
  analyst: { label: "Analyst Mode", p_title: "(Kant)" },
  misc: { label: "Misc Agent", p_title: "(for history summary)" },
};

export default function AgentsView() {
  const { providers, agentConfigs, setAgentConfigs, updateLocalAgentConfig } = useSettingsStore();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchAgentConfigs()
      .then((res) => setAgentConfigs(res.data))
      .catch((e) => console.error("Failed to fetch agent configs:", e));
  }, [setAgentConfigs]);

  // 展开所有 Provider 的所有 Model 作为可选项: "providerId:modelId"
  const availableModels = providers.flatMap((provider) =>
    provider.models.map((model) => ({
      value: `${provider.id}:${model.id}`,
      label: `${provider.display_name}/${model.name}`,
    }))
  );

  const handleModelChange = async (agentType: string, value: string) => {
    if (!value) return;
    const [providerId, modelId] = value.split(":");
    setLoading(true);
    try {
      const res = await updateAgentConfig(agentType, { provider_id: providerId, model_id: modelId });
      updateLocalAgentConfig(agentType, res.data);
    } catch (error) {
      console.error("Failed to update agent config:", error);
    } finally {
      setLoading(false);
    }
  };

  const getSelectedValue = (agentType: string) => {
    const config = agentConfigs.find((c) => c.agent_type === agentType);
    if (!config || !config.provider_id || !config.model_id) return undefined;
    
    const value = `${config.provider_id}:${config.model_id}`;
    // 防止引用的 provider 被删除导致的无效绑定
    return availableModels.some(m => m.value === value) ? value : undefined;
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6 space-y-6">
        <div>
          <h2 className="text-2xl font-semibold">Agents</h2>
          <p className="text-sm text-muted-foreground mt-1">Configure which model each agent uses</p>
        </div>

        <div className="space-y-4 max-w-2xl">
          {Object.entries(AGENT_LABELS).map(([type, { label, p_title }]) => (
            <div key={type} className="flex items-center justify-between py-4 border-b last:border-b-0">
              <div className="flex-1">
                <div className="font-medium text-base">{label}</div>
                {p_title && <div className="text-sm text-muted-foreground mt-0.5">{p_title}</div>}
              </div>
              <div className="w-[300px]">
                <Select
                  value={getSelectedValue(type) || ""}
                  onValueChange={(value) => handleModelChange(type, value)}
                  disabled={loading || availableModels.length === 0}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select a Model" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableModels.map((model) => (
                      <SelectItem key={model.value} value={model.value}>
                        {model.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}