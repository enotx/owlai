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
                <div className="flex items-center justify-between gap-2 mb-1">
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
        <Button
          variant="outline"
          className="w-full mt-4"
          onClick={handleCreate}
        >
          + New Skill
        </Button>
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

    const payload = {
      name: name.trim(),
      description: description.trim() || undefined,
      prompt_markdown: promptMarkdown || undefined,
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
      <div className="flex-1 min-h-0 overflow-y-auto p-6">
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
                        type="password"
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
      <div className="shrink-0 px-6 py-4 border-t flex justify-end gap-3">
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
  );
}