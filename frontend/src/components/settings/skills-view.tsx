// frontend/src/components/settings/skills-view.tsx

"use client";

/**
 * Skills settings view: list + editor
 */
import { useEffect, useState, useCallback } from "react";
import { useSettingsStore } from "@/stores/use-settings-store";
import {
  fetchSkills,
  createSkill,
  updateSkill,
  deleteSkill,
  exportSkill,
  importSkill,
  type SkillData,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Plus,
  Pencil,
  Trash2,
  ArrowLeft,
  Save,
  Power,
  PowerOff,
  X,
  Variable,
  Package,
  Upload, Download,
} from "lucide-react";

export default function SkillsView() {
  const {
    skills,
    setSkills,
    addSkill,
    updateSkillInStore,
    removeSkill,
    editingSkill,
    setEditingSkill,
    skillView,
    setSkillView,
  } = useSettingsStore();

  const [loading, setLoading] = useState(false);

  const loadSkills = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchSkills();
      setSkills(res.data);
    } catch {
      setSkills([]);
    } finally {
      setLoading(false);
    }
  }, [setSkills]);

  useEffect(() => {
    loadSkills();
  }, [loadSkills]);

  const handleCreate = () => {
    setEditingSkill(null);
    setSkillView("edit");
  };

  const handleEdit = (skill: SkillData) => {
    setEditingSkill(skill);
    setSkillView("edit");
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteSkill(id);
      removeSkill(id);
    } catch {
      // ignore
    }
  };

  const handleToggleActive = async (skill: SkillData) => {
    try {
      const res = await updateSkill(skill.id, {
        is_active: !skill.is_active,
      });
      updateSkillInStore(skill.id, res.data);
    } catch {
      // ignore
    }
  };

  const handleBack = () => {
    setSkillView("list");
    setEditingSkill(null);
  };

  const handleSaved = (skill: SkillData, isNew: boolean) => {
    if (isNew) {
      addSkill(skill);
    } else {
      updateSkillInStore(skill.id, skill);
    }
    setSkillView("list");
    setEditingSkill(null);
  };

  const handleImport = async () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".yaml,.yml,.json"; // 同时支持 YAML 和 JSON
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const res = await importSkill(text);
        addSkill(res.data);
      } catch (err: unknown) {
        if (
          err &&
          typeof err === "object" &&
          "response" in err &&
          (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ) {
          alert((err as { response: { data: { detail: string } } }).response.data.detail);
        } else {
          alert("Failed to import skill. Please check the file format.");
        }
      }
    };
    input.click();
  };
  
  if (skillView === "edit") {
    return (
      <SkillEditor
        skill={editingSkill}
        onBack={handleBack}
        onSaved={handleSaved}
      />
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header — fixed at top */}
      {/* Header — fixed at top */}
      <div className="shrink-0 px-6 py-4 border-b">
        <h3 className="text-lg font-semibold">Skills</h3>
      </div>

      {/* List — scrollable */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden p-6">
        {loading ? (
          <div className="text-center text-muted-foreground py-8">
            Loading...
          </div>
        ) : skills.length === 0 ? (
          <div className="text-center text-muted-foreground py-16">
            <Package className="h-12 w-12 mx-auto mb-4 opacity-40" />
            <p className="text-base mb-1">No skills configured</p>
            <p className="text-sm">
              Click &quot;New Skill&quot; to create your first skill.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {skills.map((skill) => (
              <div
                key={skill.id}
                className="border rounded-lg p-4 hover:bg-muted/30 transition-colors"
              >
                {/* Top row: name + badge + actions */}
                <div className="flex items-start sm:items-center justify-between gap-2 mb-1">
                  <div className="flex items-center gap-2 min-w-0 flex-1">
                    <span className="font-medium truncate">{skill.name}</span>
                    <Badge
                      variant={skill.is_active ? "default" : "secondary"}
                      className="text-xs shrink-0"
                    >
                      {skill.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </div>

                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      title={skill.is_active ? "Deactivate" : "Activate"}
                      onClick={() => handleToggleActive(skill)}
                    >
                      {skill.is_active ? (
                        <Power className="h-4 w-4 text-green-500" />
                      ) : (
                        <PowerOff className="h-4 w-4 text-muted-foreground" />
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => handleEdit(skill)}
                      title="Edit"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-destructive hover:text-destructive"
                      onClick={() => handleDelete(skill.id)}
                      title="Delete"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>

                {/* Description */}
                {skill.description && (
                  <p className="text-sm text-muted-foreground line-clamp-2 mb-2">
                    {skill.description}
                  </p>
                )}

                {/* Meta info */}
                <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
                  {Object.keys(skill.env_vars).length > 0 && (
                    <span className="flex items-center gap-1 shrink-0">
                      <Variable className="h-3 w-3" />
                      {Object.keys(skill.env_vars).length} env var
                      {Object.keys(skill.env_vars).length > 1 ? "s" : ""}
                    </span>
                  )}
                  {skill.reference_markdown && (
                    <span className="flex items-center gap-1 shrink-0">
                      📚 Reference
                    </span>
                  )}
                  {skill.allowed_modules.length > 0 && (
                    <span className="flex items-center gap-1 min-w-0">
                      <Package className="h-3 w-3 shrink-0" />
                      <span className="truncate max-w-[200px]">
                        {skill.allowed_modules.join(", ")}
                      </span>
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        {/* New skill button — at bottom, matching providers-list style */}
        <div className="flex gap-2 mt-4">
          <Button
            variant="outline"
            className="flex-1"
            onClick={handleImport}
          >
            <Upload className="h-4 w-4 mr-2" />
            Import Skill
          </Button>
          <Button
            variant="outline"
            className="flex-1"
            onClick={handleCreate}
          >
            <Plus className="h-4 w-4 mr-2" />
            New Skill
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ================================================================
 *  SkillEditor
 * ================================================================ */

interface SkillEditorProps {
  skill: SkillData | null;
  onBack: () => void;
  onSaved: (skill: SkillData, isNew: boolean) => void;
}

interface EnvEntry {
  key: string;
  value: string;
}

function SkillEditor({ skill, onBack, onSaved }: SkillEditorProps) {
  const isNew = !skill;

  const [name, setName] = useState(skill?.name ?? "");
  const [description, setDescription] = useState(skill?.description ?? "");
  const [promptMarkdown, setPromptMarkdown] = useState(
    skill?.prompt_markdown ?? ""
  );
  const [referenceMarkdown, setReferenceMarkdown] = useState(
    skill?.reference_markdown ?? ""
  );
  const [envEntries, setEnvEntries] = useState<EnvEntry[]>(() => {
    if (skill?.env_vars && Object.keys(skill.env_vars).length > 0) {
      return Object.entries(skill.env_vars).map(([key, value]) => ({
        key,
        value,
      }));
    }
    return [];
  });
  const [allowedModules, setAllowedModules] = useState(
    skill?.allowed_modules?.join(", ") ?? ""
  );
  const [isActive, setIsActive] = useState(skill?.is_active ?? true);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ← 新增：handler 配置
  const [handlerType, setHandlerType] = useState<"standard" | "custom_handler">(
    (skill?.handler_type as "standard" | "custom_handler") ?? "standard"
  );
  const [handlerConfig, setHandlerConfig] = useState(
    skill?.handler_config ? JSON.stringify(skill.handler_config, null, 2) : ""
  );

  const addEnvEntry = () => {
    setEnvEntries((prev) => [...prev, { key: "", value: "" }]);
  };

  const removeEnvEntry = (index: number) => {
    setEnvEntries((prev) => prev.filter((_, i) => i !== index));
  };

  const updateEnvEntry = (
    index: number,
    field: "key" | "value",
    val: string
  ) => {
    setEnvEntries((prev) =>
      prev.map((entry, i) =>
        i === index ? { ...entry, [field]: val } : entry
      )
    );
  };

  const handleSave = async () => {
    if (!name.trim()) {
      setError("Name is required");
      return;
    }

    setSaving(true);
    setError(null);

    const envVars: Record<string, string> = {};
    for (const entry of envEntries) {
      const k = entry.key.trim();
      if (k) {
        envVars[k] = entry.value;
      }
    }

    const modules = allowedModules
      .split(",")
      .map((m) => m.trim())
      .filter(Boolean);

    // ← 解析 handler_config
    let parsedHandlerConfig: Record<string, unknown> | undefined;
    if (handlerType === "custom_handler" && handlerConfig.trim()) {
      try {
        parsedHandlerConfig = JSON.parse(handlerConfig);
      } catch {
        setError("Invalid handler config JSON");
        return;
      }
    }
    const payload = {
      name: name.trim(),
      description: description.trim() || undefined,
      prompt_markdown: promptMarkdown || undefined,
      reference_markdown: referenceMarkdown || undefined,
      handler_type: handlerType,
      handler_config: parsedHandlerConfig,
      env_vars: envVars,
      allowed_modules: modules,
      is_active: isActive,
    };

    try {
      if (isNew) {
        const res = await createSkill(payload);
        onSaved(res.data, true);
      } else {
        const res = await updateSkill(skill!.id, payload);
        onSaved(res.data, false);
      }
    } catch (err: unknown) {
      if (
        err &&
        typeof err === "object" &&
        "response" in err &&
        (err as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail
      ) {
        setError(
          (err as { response: { data: { detail: string } } }).response.data
            .detail
        );
      } else {
        setError("Failed to save skill");
      }
    } finally {
      setSaving(false);
    }
  };

  const handleExport = async () => {
    if (!skill) return;
    try {
      await exportSkill(skill.id);
    } catch {
      setError("Failed to export skill");
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header — fixed */}
      <div className="shrink-0 px-6 py-4 border-b flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={onBack} className="shrink-0">
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h3 className="text-lg font-semibold truncate">
          {isNew ? "New Skill" : `Edit Skill: ${skill!.name}`}
        </h3>
      </div>

      {/* Error message */}
      {error && (
        <div className="shrink-0 mx-6 mt-4 p-3 bg-destructive/10 border border-destructive/30 text-destructive text-sm rounded-md">
          {error}
        </div>
      )}

      {/* Scrollable form — takes remaining space */}
      <div className="flex-1 min-h-0 overflow-y-auto p-6 sm:p-6">
        <div className="max-w-2xl space-y-6">
          {/* Name + Allowed Modules */}
          <div>
            <label className="text-sm font-medium mb-1.5 block">
              Name <span className="text-destructive">*</span>
            </label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. yfinance"
            />
          </div>

          <div>
            <label className="text-sm font-medium mb-1.5 block">
              Allowed Modules
            </label>
            <Input
              value={allowedModules}
              onChange={(e) => setAllowedModules(e.target.value)}
              placeholder="e.g. yfinance, pandas (comma separated)"
            />
            <p className="text-xs text-muted-foreground mt-1">
              Additional Python modules allowed in the sandbox, separated by
              commas.
            </p>
          </div>

          <div>
            <label className="text-sm font-medium mb-1.5 block">
              Handler Type
            </label>
            <select
              value={handlerType}
              onChange={(e) => setHandlerType(e.target.value as "standard" | "custom_handler")}
              className="w-full px-3 py-2 border rounded-md"
              disabled={skill?.is_system} // 系统 skill 不可修改
            >
              <option value="standard">Standard (LLM + Tools)</option>
              <option value="custom_handler">Custom Handler (ReACT)</option>
            </select>
            <p className="text-xs text-muted-foreground mt-1">
              Standard: Skill prompt injected into system prompt. Custom: Dedicated handler with ReACT loop.
            </p>
          </div>

          {handlerType === "custom_handler" && (
            <div>
              <label className="text-sm font-medium mb-1.5 block">
                Handler Config (JSON)
              </label>
              <Textarea
                value={handlerConfig}
                onChange={(e) => setHandlerConfig(e.target.value)}
                placeholder={`{
            "handler_name": "derive_pipeline",
            "max_react_rounds": 3,
            "require_hitl_confirmation": true
          }`}
                className="h-[120px] w-full font-mono text-sm"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Configuration for the custom handler (JSON format).
              </p>
            </div>
          )}

          <div>
            <label className="text-sm font-medium mb-1.5 block">
              Description
            </label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Get stock quotes, financial data, market news, and portfolio analytics from Yahoo Finance."
            />
          </div>

          <Separator />

          {/* Prompt markdown */}
          <div>
            <label className="text-sm font-medium mb-1.5 block">
              Skill Prompt (Markdown)
            </label>
            <p className="text-xs text-muted-foreground mb-2">
              Explain how the agent should use this skill, including imports,
              key APIs, usage patterns, and expected outputs.
            </p>
            <Textarea
              value={promptMarkdown}
              onChange={(e) => setPromptMarkdown(e.target.value)}
              placeholder={`Description: Get stock quotes, financial data, market news, and portfolio analytics from Yahoo Finance. Use when you need real-time stock prices, historical data, company financials, crypto prices, or market analysis.

## Quick Stock Quote

Get current price:
\`\`\`python
import yfinance as yf

t = yf.Ticker("AAPL")
print(f"Price: $\{t.info.get('currentPrice', t.info.get('regularMarketPrice'))}")
\`\`\`

Multiple tickers:
\`\`\`python
import yfinance as yf

tickers = yf.Tickers("AAPL MSFT GOOGL TSLA")
for t in ["AAPL", "MSFT", "GOOGL", "TSLA"]:
    info = tickers.tickers[t].info
    print(f"{t}: $\{info.get('currentPrice', info.get('regularMarketPrice', 'N/A'))}")
\`\`\`

## Historical Data

Download historical prices:
\`\`\`python
import yfinance as yf

data = yf.download("AAPL", period="1mo", interval="1d")
print(data.tail(10))
\`\`\`
`}
              className="h-[200px] w-full font-mono text-sm leading-relaxed resize-none overflow-y-auto"
            />
          </div>
          <Separator />

          {/* Reference documentation — NEW */}
          <div>
            <label className="text-sm font-medium mb-1.5 block">
              Reference Documentation
              <Badge variant="secondary" className="ml-2 text-xs font-normal">
                Lazy-loaded
              </Badge>
            </label>
            <p className="text-xs text-muted-foreground mb-2">
              Detailed API reference, parameter specs, and advanced usage patterns.
              This is <strong>not</strong> injected into the system prompt — the agent
              will fetch it on-demand via a tool call when needed.
            </p>
            <Textarea
              value={referenceMarkdown}
              onChange={(e) => setReferenceMarkdown(e.target.value)}
              placeholder={`## API Reference
### get_stock_price(symbol: str) -> dict
Returns current price data for the given ticker symbol.
**Parameters:**
- \`symbol\` (str): Ticker symbol, e.g. "AAPL"
**Returns:** dict with keys: currentPrice, previousClose, volume, ...
**Example:**
\`\`\`python
import yfinance as yf
t = yf.Ticker("AAPL")
price = t.info["currentPrice"]
\`\`\`
### Common Errors
- \`HTTPError 429\`: Rate limited — add time.sleep(1) between calls
- \`KeyError\`: Some fields may be missing for non-US stocks`}
              className="h-[200px] w-full font-mono text-sm leading-relaxed resize-none overflow-y-auto"
            />
          </div>
          <Separator />

          {/* Environment variables */}
          <div>
            <div className="mb-2">
              <label className="text-sm font-medium block">
                Environment Variables
              </label>
              <p className="text-xs text-muted-foreground">
                Runtime variables injected into the sandbox. Access them in
                agent code with{" "}
                <code className="bg-muted px-1 rounded">
                  getenv(&apos;KEY&apos;)
                </code>
                .
              </p>
            </div>

            {envEntries.length > 0 && (
              <div className="border rounded-md overflow-hidden mb-3">
                {/* Header */}
                <div className="grid grid-cols-[1fr_1fr_40px] bg-muted/50 border-b">
                  <div className="px-3 py-2 text-xs font-semibold text-muted-foreground">
                    Name
                  </div>
                  <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-l">
                    Value
                  </div>
                  <div />
                </div>

                {/* Rows */}
                {envEntries.map((entry, idx) => (
                  <div
                    key={idx}
                    className="grid grid-cols-[1fr_1fr_40px] border-b last:border-b-0"
                  >
                    <div className="px-1 py-1">
                      <Input
                        value={entry.key}
                        onChange={(e) =>
                          updateEnvEntry(idx, "key", e.target.value)
                        }
                        placeholder="YF_API_KEY"
                        className="border-0 shadow-none h-8 text-sm font-mono focus-visible:ring-0"
                      />
                    </div>
                    <div className="px-1 py-1 border-l">
                      <Input
                        value={entry.value}
                        onChange={(e) =>
                          updateEnvEntry(idx, "value", e.target.value)
                        }
                        placeholder="your_value_here"
                        className="border-0 shadow-none h-8 text-sm font-mono focus-visible:ring-0"
                        type="text"
                      />
                    </div>
                    <div className="flex items-center justify-center">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-destructive hover:text-destructive"
                        onClick={() => removeEnvEntry(idx)}
                      >
                        <X className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <Button
              variant="outline"
              size="sm"
              onClick={addEnvEntry}
              className="text-xs"
            >
              <Plus className="h-3.5 w-3.5 mr-1" />
              Add environment variable
            </Button>
          </div>
        </div>
      </div>

      {/* Bottom action bar — fixed at bottom, matching provider-form style */}
      <div className="shrink-0 px-4 sm:px-6 py-4 border-t flex flex-col-reverse sm:flex-row sm:justify-between gap-2 sm:gap-3">
        <div className="flex gap-2">
          {!isNew && (
            <Button
              variant="outline"
              onClick={handleExport}
            >
              <Download className="h-4 w-4 mr-2" />
              Export
            </Button>
          )}
        </div>
        
        <div className="flex gap-2 sm:gap-3">
          <Button
            variant="outline"
            onClick={() => setIsActive(!isActive)}
            className={
              isActive
                ? "border-green-500/50 text-green-600"
                : "border-muted text-muted-foreground"
            }
          >
            {isActive ? (
              <Power className="h-4 w-4 mr-2" />
            ) : (
              <PowerOff className="h-4 w-4 mr-2" />
            )}
            {isActive ? "Active" : "Inactive"}
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            <Save className="h-4 w-4 mr-2" />
            {saving ? "Saving..." : "Save"}
          </Button>
        </div>
      </div>
    </div>
  );
}