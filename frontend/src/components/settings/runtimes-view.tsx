// frontend/src/components/settings/runtimes-view.tsx
"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  fetchJupyterConfigs,
  createJupyterConfig,
  deleteJupyterConfig,
  testJupyterConnection,
  fetchDefaultRuntime,
  setDefaultRuntime,
  type JupyterConfigData,
} from "@/lib/api";
import {
  Loader2,
  Plus,
  Trash2,
  CheckCircle2,
  XCircle,
  Server,
  Wifi,
  Monitor,
} from "lucide-react";
import { cn } from "@/lib/utils";

export default function RuntimesView() {
  const [configs, setConfigs] = useState<JupyterConfigData[]>([]);
  const [loading, setLoading] = useState(true);
  const [defaultBackend, setDefaultBackend] = useState("local");

  // Form state
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formUrl, setFormUrl] = useState("");
  const [formToken, setFormToken] = useState("");
  const [formKernel, setFormKernel] = useState("python3");
  const [saving, setSaving] = useState(false);

  // Test state
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string }>>({});

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [configsRes, defaultRes] = await Promise.all([
        fetchJupyterConfigs(),
        fetchDefaultRuntime(),
      ]);
      setConfigs(configsRes.data);
      setDefaultBackend(defaultRes.data.value || "local");
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!formName.trim() || !formUrl.trim() || saving) return;
    setSaving(true);
    try {
      const res = await createJupyterConfig({
        name: formName.trim(),
        server_url: formUrl.trim(),
        token: formToken.trim() || undefined,
        kernel_name: formKernel,
      });
      setConfigs((prev) => [...prev, res.data]);
      setShowForm(false);
      setFormName("");
      setFormUrl("");
      setFormToken("");
      setFormKernel("python3");
    } catch (err) {
      console.error("Failed to create runtime:", err);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteJupyterConfig(id);
      setConfigs((prev) => prev.filter((c) => c.id !== id));
      // If deleted config was default, reset to local
      if (defaultBackend === `jupyter:${id}`) {
        await setDefaultRuntime("local");
        setDefaultBackend("local");
      }
    } catch (err) {
      console.error("Failed to delete runtime:", err);
    }
  };

  const handleTest = async (id: string) => {
    setTestingId(id);
    try {
      const res = await testJupyterConnection(id);
      setTestResults((prev) => ({ ...prev, [id]: res.data }));
    } catch {
      setTestResults((prev) => ({
        ...prev,
        [id]: { success: false, message: "Connection failed" },
      }));
    } finally {
      setTestingId(null);
    }
  };

  const handleSetDefault = async (value: string) => {
    try {
      await setDefaultRuntime(value);
      setDefaultBackend(value);
    } catch (err) {
      console.error("Failed to set default runtime:", err);
    }
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      {/* Global Default */}
      <div className="space-y-2">
        <h3 className="text-sm font-semibold">Default Runtime</h3>
        <p className="text-xs text-muted-foreground">
          New tasks will use this runtime by default.
        </p>
        <Select value={defaultBackend} onValueChange={handleSetDefault}>
          <SelectTrigger className="w-64">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="local">
              <span className="flex items-center gap-2">
                <Monitor className="h-3.5 w-3.5" />
                Local (built-in sandbox)
              </span>
            </SelectItem>
            {configs.map((c) => (
              <SelectItem key={c.id} value={`jupyter:${c.id}`}>
                <span className="flex items-center gap-2">
                  <Server className="h-3.5 w-3.5" />
                  {c.name}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Jupyter Configs */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Jupyter Servers</h3>
          <Button size="sm" variant="outline" onClick={() => setShowForm(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            Add
          </Button>
        </div>

        {/* Create Form */}
        {showForm && (
          <div className="rounded-lg border p-4 space-y-3 bg-muted/20">
            <Input
              placeholder="Name (e.g. GPU Server)"
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
            />
            <Input
              placeholder="Server URL (e.g. http://gpu-server:8888)"
              value={formUrl}
              onChange={(e) => setFormUrl(e.target.value)}
            />
            <Input
              placeholder="Token (optional)"
              type="password"
              value={formToken}
              onChange={(e) => setFormToken(e.target.value)}
            />
            <Input
              placeholder="Kernel name (default: python3)"
              value={formKernel}
              onChange={(e) => setFormKernel(e.target.value)}
            />
            <div className="flex gap-2 justify-end">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowForm(false)}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={handleCreate}
                disabled={!formName.trim() || !formUrl.trim() || saving}
              >
                {saving && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
                Save
              </Button>
            </div>
          </div>
        )}

        {/* Config List */}
        {configs.length === 0 && !showForm && (
          <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            No Jupyter servers configured yet.
          </div>
        )}

        {configs.map((config) => (
          <div
            key={config.id}
            className="rounded-lg border p-4 space-y-2"
          >
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <Server className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium text-sm">{config.name}</span>
                  <span
                    className={cn(
                      "inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium",
                      config.status === "active"
                        ? "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300"
                        : "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
                    )}
                  >
                    {config.status}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  {config.server_url} · kernel: {config.kernel_name}
                </p>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleTest(config.id)}
                  disabled={testingId === config.id}
                >
                  {testingId === config.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Wifi className="h-3.5 w-3.5" />
                  )}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleDelete(config.id)}
                  className="text-destructive hover:text-destructive"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>

            {/* Test Result */}
            {testResults[config.id] && (
              <div
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-xs",
                  testResults[config.id].success
                    ? "bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300"
                    : "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300"
                )}
              >
                {testResults[config.id].success ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : (
                  <XCircle className="h-3.5 w-3.5" />
                )}
                {testResults[config.id].message}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}