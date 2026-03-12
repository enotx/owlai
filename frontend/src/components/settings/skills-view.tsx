// frontend/src/components/settings/skills-view.tsx

"use client";

/**
 * Skills 管理视图：列表 + 编辑（Portainer 风格）
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

  // 加载 Skills 列表
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

  // 新建
  const handleCreate = () => {
    setEditingSkill(null);
    setSkillView("edit");
  };

  // 编辑
  const handleEdit = (skill: SkillData) => {
    setEditingSkill(skill);
    setSkillView("edit");
  };

  // 删除
  const handleDelete = async (id: string) => {
    try {
      await deleteSkill(id);
      removeSkill(id);
    } catch {
      // ignore
    }
  };

  // 切换激活状态
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

  // 返回列表
  const handleBack = () => {
    setSkillView("list");
    setEditingSkill(null);
  };

  // 保存回调
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
    <div className="h-full flex flex-col">
      {/* 头部 */}
      <div className="flex items-center justify-between p-6 pb-4">
        <div>
          <h3 className="text-lg font-semibold">Skills</h3>
          <p className="text-sm text-muted-foreground">
            配置 Agent 可使用的扩展技能（私有包、外部 API 等）
          </p>
        </div>
        <Button size="sm" onClick={handleCreate}>
          <Plus className="h-4 w-4 mr-1" />
          New Skill
        </Button>
      </div>
      <Separator />

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="text-center text-muted-foreground py-8">
            Loading...
          </div>
        ) : skills.length === 0 ? (
          <div className="text-center text-muted-foreground py-16">
            <Package className="h-12 w-12 mx-auto mb-4 opacity-40" />
            <p className="text-base mb-1">No skills configured</p>
            <p className="text-sm">
              点击 &quot;New Skill&quot; 添加第一个扩展技能
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {skills.map((skill) => (
              <div
                key={skill.id}
                className="border rounded-lg p-4 flex items-start justify-between gap-4 hover:bg-muted/30 transition-colors"
              >
                {/* 左侧信息 */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium truncate">{skill.name}</span>
                    <Badge
                      variant={skill.is_active ? "default" : "secondary"}
                      className="text-xs shrink-0"
                    >
                      {skill.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </div>
                  {skill.description && (
                    <p className="text-sm text-muted-foreground truncate mb-2">
                      {skill.description}
                    </p>
                  )}
                  <div className="flex items-center gap-4 text-xs text-muted-foreground">
                    {/* 环境变量数量 */}
                    {Object.keys(skill.env_vars).length > 0 && (
                      <span className="flex items-center gap-1">
                        <Variable className="h-3 w-3" />
                        {Object.keys(skill.env_vars).length} env var
                        {Object.keys(skill.env_vars).length > 1 ? "s" : ""}
                      </span>
                    )}
                    {/* 额外模块数量 */}
                    {skill.allowed_modules.length > 0 && (
                      <span className="flex items-center gap-1">
                        <Package className="h-3 w-3" />
                        {skill.allowed_modules.join(", ")}
                      </span>
                    )}
                  </div>
                </div>

                {/* 右侧操作按钮 */}
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
                  >
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-destructive hover:text-destructive"
                    onClick={() => handleDelete(skill.id)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ================================================================
 *  SkillEditor — Portainer 风格编辑器
 *  上半：Markdown 编辑区
 *  下半：环境变量 Key/Value 表格
 * ================================================================ */

interface SkillEditorProps {
  skill: SkillData | null; // null = 新建
  onBack: () => void;
  onSaved: (skill: SkillData, isNew: boolean) => void;
}

interface EnvEntry {
  key: string;
  value: string;
}

function SkillEditor({ skill, onBack, onSaved }: SkillEditorProps) {
  const isNew = !skill;

  // 表单状态
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

  // 环境变量操作
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

  // 保存
  const handleSave = async () => {
    if (!name.trim()) {
      setError("Name is required");
      return;
    }

    setSaving(true);
    setError(null);

    // 组装 env_vars 字典（过滤空 key）
    const envVars: Record<string, string> = {};
    for (const entry of envEntries) {
      const k = entry.key.trim();
      if (k) {
        envVars[k] = entry.value;
      }
    }

    // 解析 allowed_modules
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
    <div className="h-full flex flex-col">
      {/* 顶栏 */}
      <div className="flex items-center justify-between p-6 pb-4">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h3 className="text-lg font-semibold">
            {isNew ? "New Skill" : `Edit: ${skill!.name}`}
          </h3>
        </div>
        <div className="flex items-center gap-2">
          {/* 激活/停用切换 */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setIsActive(!isActive)}
            className={
              isActive
                ? "border-green-500/50 text-green-600"
                : "border-muted text-muted-foreground"
            }
          >
            {isActive ? (
              <Power className="h-3.5 w-3.5 mr-1" />
            ) : (
              <PowerOff className="h-3.5 w-3.5 mr-1" />
            )}
            {isActive ? "Active" : "Inactive"}
          </Button>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            <Save className="h-4 w-4 mr-1" />
            {saving ? "Saving..." : "Save"}
          </Button>
        </div>
      </div>
      <Separator />

      {/* 错误提示 */}
      {error && (
        <div className="mx-6 mt-4 p-3 bg-destructive/10 border border-destructive/30 text-destructive text-sm rounded-md">
          {error}
        </div>
      )}

      {/* 编辑区域（可滚动） */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* 基础信息 */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-sm font-medium mb-1.5 block">
              Name <span className="text-destructive">*</span>
            </label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. pytalos_query"
            />
          </div>
          <div>
            <label className="text-sm font-medium mb-1.5 block">
              Allowed Modules
            </label>
            <Input
              value={allowedModules}
              onChange={(e) => setAllowedModules(e.target.value)}
              placeholder="e.g. pytalos, requests (comma separated)"
            />
            <p className="text-xs text-muted-foreground mt-1">
              沙箱中额外放行的 Python 模块（逗号分隔）
            </p>
          </div>
        </div>

        <div>
          <label className="text-sm font-medium mb-1.5 block">
            Description
          </label>
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="简短描述该技能的用途"
          />
        </div>

        {/* Prompt Markdown 编辑器 */}
        <div>
          <label className="text-sm font-medium mb-1.5 block">
            Skill Prompt (Markdown)
          </label>
          <p className="text-xs text-muted-foreground mb-2">
            告诉 Agent 如何使用该技能。包含：库的导入方式、关键 API
            调用示例、返回值格式说明等。
          </p>
          <Textarea
            value={promptMarkdown}
            onChange={(e) => setPromptMarkdown(e.target.value)}
            placeholder={`# pytalos 使用说明\n\n## 初始化\n\`\`\`python\nfrom pytalos.client import AsyncTalosClient, SDKScene\nclient = AsyncTalosClient(getenv("TALOS_USER"), getenv("TALOS_TOKEN"), sdk_scene=SDKScene.MIS)\nclient.open_session()\n\`\`\`\n\n## 提交查询\n...\n`}
            className="min-h-[280px] font-mono text-sm leading-relaxed"
          />
        </div>

        {/* 环境变量配置（Portainer 风格） */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <div>
              <label className="text-sm font-medium block">
                Environment Variables
              </label>
              <p className="text-xs text-muted-foreground">
                运行时注入沙箱的环境变量。Agent 代码中通过{" "}
                <code className="bg-muted px-1 rounded">
                  getenv(&apos;KEY&apos;)
                </code>{" "}
                读取。
              </p>
            </div>
          </div>

          {/* 变量表格 */}
          {envEntries.length > 0 && (
            <div className="border rounded-md overflow-hidden mb-3">
              {/* 表头 */}
              <div className="grid grid-cols-[1fr_1fr_40px] gap-0 bg-muted/50 border-b">
                <div className="px-3 py-2 text-xs font-semibold text-muted-foreground">
                  name
                </div>
                <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-l">
                  value
                </div>
                <div />
              </div>
              {/* 行 */}
              {envEntries.map((entry, idx) => (
                <div
                  key={idx}
                  className="grid grid-cols-[1fr_1fr_40px] gap-0 border-b last:border-b-0"
                >
                  <div className="px-1 py-1">
                    <Input
                      value={entry.key}
                      onChange={(e) =>
                        updateEnvEntry(idx, "key", e.target.value)
                      }
                      placeholder="TALOS_USER"
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
            Add an environment variable
          </Button>
        </div>
      </div>
    </div>
  );
}