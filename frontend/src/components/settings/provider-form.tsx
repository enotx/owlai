// frontend/src/components/settings/provider-form.tsx

"use client";

/**
 * Provider 编辑/新建表单
 */
import { useState, useEffect } from "react";
import { useSettingsStore, type LLMModel } from "@/stores/use-settings-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createProvider, updateProvider, testConnection } from "@/lib/api";
import { ArrowLeft, Loader2, X } from "lucide-react";
import { Separator } from "@/components/ui/separator";

export default function ProviderForm() {
  const {
    editingProvider,
    setCurrentView,
    addProvider,
    updateProvider: updateStoreProvider,
  } = useSettingsStore();

  const [displayName, setDisplayName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState<LLMModel[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  // 初始化表单
  useEffect(() => {
    if (editingProvider) {
      setDisplayName(editingProvider.display_name);
      setBaseUrl(editingProvider.base_url);
      setApiKey(editingProvider.api_key || "");
      setModels(editingProvider.models);
    } else {
      setDisplayName("");
      setBaseUrl("");
      setApiKey("");
      setModels([]);
    }
  }, [editingProvider]);

  const handleBack = () => {
    setCurrentView("list");
  };

  const handleAddModel = () => {
    setModels([...models, { id: "", name: "" }]);
  };

  const handleRemoveModel = (index: number) => {
    setModels(models.filter((_, i) => i !== index));
  };

  const handleModelChange = (
    index: number,
    field: "id" | "name",
    value: string
  ) => {
    const updated = [...models];
    updated[index][field] = value;
    setModels(updated);
  };

  const handleTestConnection = async () => {
    if (!baseUrl) {
      setTestResult({ success: false, message: "Base URL is required" });
      return;
    }

    setIsTesting(true);
    setTestResult(null);

    try {
      const res = await testConnection({
        base_url: baseUrl,
        api_key: apiKey || undefined,
      });
      setTestResult({
        success: res.data.success,
        message: res.data.message,
      });
    } catch (err) {
      setTestResult({
        success: false,
        message: "Connection test failed",
      });
    } finally {
      setIsTesting(false);
    }
  };

  const handleSave = async () => {
    if (!displayName || !baseUrl) {
      alert("Display name and Base URL are required");
      return;
    }

    setIsSaving(true);
    try {
      const data = {
        display_name: displayName,
        base_url: baseUrl,
        api_key: apiKey || undefined,
        models: models.filter((m) => m.id && m.name),
      };

      if (editingProvider) {
        const res = await updateProvider(editingProvider.id, data);
        updateStoreProvider(editingProvider.id, res.data);
      } else {
        const res = await createProvider(data);
        addProvider(res.data);
      }

      setCurrentView("list");
    } catch (err) {
      alert("Failed to save provider");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* 头部 */}
      <div className="px-6 py-4 border-b flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={handleBack}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h3 className="text-lg font-semibold">
          {editingProvider ? "Edit Provider" : "New Provider"}
        </h3>
      </div>

      {/* 表单 */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl space-y-6">
          {/* Display Name */}
          <div>
            <label className="text-sm font-medium mb-2 block">
              Display name
            </label>
            <Input
              placeholder="My AI Provider"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </div>

          {/* Base URL */}
          <div>
            <label className="text-sm font-medium mb-2 block">Base URL</label>
            <Input
              placeholder="https://api.myprovider.com/v1"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </div>

          {/* API Key */}
          <div>
            <label className="text-sm font-medium mb-2 block">API key</label>
            <Input
              type="password"
              placeholder="API key"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <p className="text-xs text-muted-foreground mt-1">
              Optional. Leave empty if you manage auth via headers.
            </p>
          </div>

          <Separator />

          {/* Models */}
          <div>
            <label className="text-sm font-medium mb-2 block">Models</label>
            <div className="space-y-2">
              {models.map((model, index) => (
                <div key={index} className="flex flex-col sm:flex-row gap-2">
                  <Input
                    placeholder="model-id"
                    value={model.id}
                    onChange={(e) =>
                      handleModelChange(index, "id", e.target.value)
                    }
                    className="flex-1"
                  />
                  <Input
                    placeholder="Display Name"
                    value={model.name}
                    onChange={(e) =>
                      handleModelChange(index, "name", e.target.value)
                    }
                    className="flex-1"
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleRemoveModel(index)}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={handleAddModel}
            >
              + Add model
            </Button>
          </div>

          {/* Test Connection Result */}
          {testResult && (
            <div
              className={`p-3 rounded-md text-sm ${
                testResult.success
                  ? "bg-green-50 text-green-800 border border-green-200"
                  : "bg-red-50 text-red-800 border border-red-200"
              }`}
            >
              {testResult.message}
            </div>
          )}
        </div>
      </div>

      {/* 底部操作栏 */}
      <div className="px-4 sm:px-6 py-4 border-t flex flex-col-reverse sm:flex-row sm:justify-end gap-2 sm:gap-3">
        <Button
          variant="outline"
          onClick={handleTestConnection}
          disabled={isTesting || !baseUrl}
        >
          {isTesting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
          Test Connection
        </Button>
        <Button onClick={handleSave} disabled={isSaving}>
          {isSaving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
          Save
        </Button>
      </div>
    </div>
  );
}