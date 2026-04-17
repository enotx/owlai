// frontend/src/components/chat/message-input.tsx
"use client";
import * as React from "react";
import { useState, useRef, useEffect, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SendHorizonal, Square, Database, FileText, FileCode2 } from "lucide-react";
import { streamChat, autoRenameTask } from "@/lib/api";
import type { SSEEvent } from "@/lib/api";
import { useTaskStore, Step } from "@/stores/use-task-store";
import { useSettingsStore } from "@/stores/use-settings-store";
import { cn } from "@/lib/utils";
import { fetchSkills, type SkillData } from "@/lib/api";
import { Zap } from "lucide-react";
import ContextRing from "./context-ring";


// ── Slash Command Definitions ─────────────────────────────
// ── Dynamic Slash Command from Skills ─────────────────
interface SlashCommand {
  command: string;     // e.g. "/derive"
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  group: "System" | "Custom";
  isActive: boolean;
  skillId: string;
}
const DEFAULT_MODEL_VALUE = "__use_default__";
export default function MessageInput() {
  // Dynamic slash commands from skills
  const [slashCommands, setSlashCommands] = useState<SlashCommand[]>([]);
  const [slashCommandsLoaded, setSlashCommandsLoaded] = useState(false);

  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const autoRenameCalledRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  // Slash command state
  const [showSlashMenu, setShowSlashMenu] = useState(false);
  const [slashFilter, setSlashFilter] = useState("");
  const [slashSelectedIndex, setSlashSelectedIndex] = useState(0);
  const slashMenuRef = useRef<HTMLDivElement>(null);

  // Load skills for slash commands
  useEffect(() => {
    let cancelled = false;
    const loadSkills = async () => {
      try {
        const res = await fetchSkills();
        if (cancelled) return;
        const skills: SkillData[] = res.data;
        const cmds: SlashCommand[] = skills.map((skill) => {
          const cmd = skill.slash_command || skill.name.toLowerCase().replace(/\s+/g, "_");
          return {
            command: `/${cmd}`,
            label: skill.name,
            description: skill.description || "",
            icon: skill.is_system ? Database : Zap,
            group: skill.is_system ? "System" : "Custom",
            isActive: skill.is_active,
            skillId: skill.id,
          };
        });
        setSlashCommands(cmds);
        setSlashCommandsLoaded(true);
      } catch {
        // fallback: empty
        setSlashCommandsLoaded(true);
      }
    };
    loadSkills();
    return () => { cancelled = true; };
  }, []);

  const {
    currentTaskId,
    addStep,
    isSending,
    setIsSending,
    getCurrentPendingTool,
    isWaitingResponse,
    setIsWaitingResponse,
    startStreaming,
    appendStreamingToken,
    clearStreaming,
    setPendingTool,
    updatePendingToolResult,
    currentMode,
    setCurrentMode,
    selectedModel,
    setSelectedModel,
    steps,
    isExecuting,
    setIsExecuting,
    tasks,
    isTaskReady,
  } = useTaskStore();

  const { providers, agentConfigs } = useSettingsStore();

  // Build available models list
  const availableModels = providers.flatMap((provider) =>
    provider.models.map((model) => ({
      value: `${provider.id}:${model.id}`,
      label: `${provider.display_name}/${model.name}`,
      providerId: provider.id,
      modelId: model.id,
    }))
  );

  // 获取当前 task 的 task_type
  const currentTask = useMemo(
    () => tasks.find((t) => t.id === currentTaskId),
    [tasks, currentTaskId]
  );
  const taskType = (currentTask as any)?.task_type || "ad_hoc";
  const taskReady = isTaskReady(currentTaskId);


  // Filter slash commands based on typed text
  const filteredCommands = useMemo(() => {
    if (!slashFilter) return [...slashCommands];
    const lower = slashFilter.toLowerCase();
    return slashCommands.filter(
      (cmd) =>
        cmd.command.slice(1).toLowerCase().startsWith(lower) ||
        cmd.label.toLowerCase().includes(lower)
    );
  }, [slashFilter, slashCommands]);

  // Detect active slash command in text (for badge display)
  const activeCommand = useMemo(() => {
    const trimmed = text.trimStart();
    for (const cmd of slashCommands) {
      if (
        trimmed.startsWith(cmd.command + " ") ||
        trimmed === cmd.command
      ) {
        return cmd;
      }
    }
    return null;
  }, [text, slashCommands]);



  const getDefaultModelForMode = (mode: string) => {
    const agentTypeMap: Record<string, string> = {
      auto: "default",
      plan: "plan",
      analyst: "analyst",
    };
    const agentType = agentTypeMap[mode] || "default";
    const config = agentConfigs.find((c) => c.agent_type === agentType);
    if (!config || !config.provider_id || !config.model_id) return null;
    return { providerId: config.provider_id, modelId: config.model_id };
  };

  const getDisplayModel = () => {
    if (selectedModel) {
      const found = availableModels.find(
        (m) =>
          m.providerId === selectedModel.providerId &&
          m.modelId === selectedModel.modelId
      );
      return found ? found.label : "Unknown";
    }
    const defaultModel = getDefaultModelForMode(currentMode);
    if (!defaultModel) return "Not configured";
    const found = availableModels.find(
      (m) =>
        m.providerId === defaultModel.providerId &&
        m.modelId === defaultModel.modelId
    );
    return found ? found.label : "Unknown";
  };

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 160) + "px";
    }
  }, [text]);

  // Close slash menu on click outside
  useEffect(() => {
    if (!showSlashMenu) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (
        slashMenuRef.current &&
        !slashMenuRef.current.contains(e.target as Node)
      ) {
        setShowSlashMenu(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showSlashMenu]);

  // ── Slash command detection ─────────────────────────────
  const handleTextChange = (value: string) => {
    setText(value);

    const cursorPos = textareaRef.current?.selectionStart ?? value.length;
    const textBeforeCursor = value.slice(0, cursorPos);

    // Only trigger at the very start of input: /xxx
    const slashMatch = textBeforeCursor.match(/^\/(\w*)$/);

    if (slashMatch) {
      setSlashFilter(slashMatch[1]);
      setShowSlashMenu(true);
      setSlashSelectedIndex(0);
    } else {
      setShowSlashMenu(false);
    }
  };

  const selectSlashCommand = (cmd: SlashCommand) => {
    setText(cmd.command + " ");
    setShowSlashMenu(false);
    textareaRef.current?.focus();
  };

  /** Handle clicking the Extract button (external trigger) */
  const handleExtractClick = (cmd: SlashCommand) => {
    setText(cmd.command + " ");
    setShowSlashMenu(false);
    // Focus and place cursor at end
    setTimeout(() => {
      const el = textareaRef.current;
      if (el) {
        el.focus();
        el.selectionStart = el.selectionEnd = el.value.length;
      }
    }, 0);
  };

  // ── Abort ───────────────────────────────────────────────
  const handleAbort = () => {
    try {
      abortControllerRef.current?.abort();
    } catch {
      // AbortError expected
    }
    abortControllerRef.current = null;
    clearStreaming();
    setPendingTool(currentTaskId!, null);
    setIsWaitingResponse(false);
    setIsSending(false);
  };

  // ── Send ────────────────────────────────────────────────
  const handleSend = async () => {
    if (!text.trim() || !currentTaskId || isSending) return;
    const message = text.trim();
    setText("");
    autoRenameCalledRef.current = false;
    setIsSending(true);
    setIsWaitingResponse(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const tempUserId = `temp-user-${Date.now()}`;
    addStep({
      id: tempUserId,
      task_id: currentTaskId,
      role: "user",
      step_type: "user_message",
      content: message,
      code: null,
      code_output: null,
      created_at: new Date().toISOString(),
    });

    try {
      const modelOverride = selectedModel
        ? {
            provider_id: selectedModel.providerId,
            model_id: selectedModel.modelId,
          }
        : undefined;

      await streamChat(
        currentTaskId,
        message,
        (event: SSEEvent) => {
          switch (event.type) {
            case "text":
              if (useTaskStore.getState().isWaitingResponse) {
                setIsWaitingResponse(false);
              }
              if (!useTaskStore.getState().streamingMessage) {
                startStreaming();
              }
              if (event.content) {
                appendStreamingToken(event.content);
              }
              break;

            case "tool_start":
              if (useTaskStore.getState().isWaitingResponse) {
                setIsWaitingResponse(false);
              }
              _flushStreaming();
              setPendingTool(currentTaskId!, {
                code: event.code || "",
                purpose: event.purpose || "",
                status: "running",
              });
              break;

            case "tool_result":
              updatePendingToolResult(currentTaskId!, {
                success: event.success ?? false,
                output: event.output ?? null,
                error: event.error ?? null,
                time: event.time ?? 0,
                dataframes: event.dataframes,
              });
              break;

            case "step_saved": {
              const step = event.step as unknown as Step;
              if (step.step_type === "user_message") {
                const store = useTaskStore.getState();
                const updatedSteps = store.steps.map((s) =>
                  s.id === tempUserId ? step : s
                );
                useTaskStore.setState({ steps: updatedSteps });
              } else {
                clearStreaming();
                setPendingTool(currentTaskId!, null);
                addStep(step);

                if (step.step_type === "hitl_request" && step.code_output) {
                  try {
                    const hitlData = JSON.parse(step.code_output);
                    useTaskStore.getState().setPendingHITL({
                      stepId: step.id,
                      data: hitlData,
                    });
                  } catch {
                    // ignore
                  }
                }
              }
              break;
            }

            case "visualization":
              break;

            case "hitl_request":
              break;

            case "done": {
              clearStreaming();
              setPendingTool(currentTaskId!, null);
              if (!autoRenameCalledRef.current) {
                autoRenameCalledRef.current = true;
                const store = useTaskStore.getState();
                const currentTask = store.tasks.find(
                  (t) => t.id === currentTaskId
                );
                if (currentTask && /^Task \d+$/.test(currentTask.title)) {
                  autoRenameTask(currentTaskId!)
                    .then((res) => {
                      const newTitle = res.data?.title;
                      if (newTitle && newTitle !== currentTask.title) {
                        useTaskStore
                          .getState()
                          .updateTaskTitle(currentTaskId!, newTitle);
                      }
                    })
                    .catch((err) => {
                      console.error("Auto-rename failed:", err);
                    });
                }
              }
              break;
            }

            case "error":
              clearStreaming();
              setPendingTool(currentTaskId!, null);
              setIsWaitingResponse(false);
              addStep({
                id: `error-${Date.now()}`,
                task_id: currentTaskId!,
                role: "assistant",
                step_type: "assistant_message",
                content: `⚠️ ${event.content || "Unknown error"}`,
                code: null,
                code_output: null,
                created_at: new Date().toISOString(),
              });
              break;
          }
        },
        currentMode,
        modelOverride,
        controller
      );
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        // silent
      } else {
        console.error("Stream failed:", err);
        clearStreaming();
        setPendingTool(currentTaskId!, null);
        setIsWaitingResponse(false);
        addStep({
          id: `error-${Date.now()}`,
          task_id: currentTaskId,
          role: "assistant",
          step_type: "assistant_message",
          content: "⚠️ 网络请求失败,请检查后端是否正常运行。",
          code: null,
          code_output: null,
          created_at: new Date().toISOString(),
        });
      }
    } finally {
      abortControllerRef.current = null;
      setIsSending(false);
      setIsWaitingResponse(false);
    }
  };

  const handleExecute = async () => {
    if (!currentTaskId || isExecuting) return;
    setIsExecuting(true);
    setIsWaitingResponse(true);

    const controller = new AbortController();

    try {
      const { executeTask } = await import("@/lib/api");

      await executeTask(
        currentTaskId,
        (event: SSEEvent) => {
          switch (event.type) {
            case "text":
              if (useTaskStore.getState().isWaitingResponse) {
                setIsWaitingResponse(false);
              }
              if (!useTaskStore.getState().streamingMessage) {
                startStreaming();
              }
              if (event.content) appendStreamingToken(event.content);
              break;

            case "tool_start":
              if (useTaskStore.getState().isWaitingResponse) {
                setIsWaitingResponse(false);
              }
              clearStreaming();
              setPendingTool(currentTaskId!, {
                code: event.code || "",
                purpose: event.purpose || "",
                status: "running",
              });
              break;

            case "tool_result":
              updatePendingToolResult(currentTaskId!, {
                success: event.success ?? false,
                output: event.output ?? null,
                error: event.error ?? null,
                time: event.time ?? 0,
                dataframes: event.dataframes,
              });
              break;

            case "step_saved": {
              const step = event.step as unknown as Step;
              clearStreaming();
              setPendingTool(currentTaskId!, null);
              addStep(step);
              break;
            }

            case "done":
              clearStreaming();
              setPendingTool(currentTaskId!, null);
              setIsWaitingResponse(false);
              break;

            case "error":
              clearStreaming();
              setPendingTool(currentTaskId!, null);
              setIsWaitingResponse(false);
              addStep({
                id: `error-${Date.now()}`,
                task_id: currentTaskId!,
                role: "assistant",
                step_type: "assistant_message",
                content: `⚠️ ${event.content || "Unknown error"}`,
                code: null,
                code_output: null,
                created_at: new Date().toISOString(),
              });
              break;
          }
        },
        {
          user_message: text.trim() || undefined,
        },
        controller,
      );
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        console.error("Execute failed:", err);
      }
    } finally {
      setIsExecuting(false);
      setIsWaitingResponse(false);
      setText("");
    }
  };

  function _flushStreaming() {
    clearStreaming();
  }

  // ── Keyboard handling ───────────────────────────────────
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Slash menu navigation
    if (showSlashMenu && filteredCommands.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSlashSelectedIndex((i) =>
          Math.min(i + 1, filteredCommands.length - 1)
        );
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSlashSelectedIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        selectSlashCommand(filteredCommands[slashSelectedIndex]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setShowSlashMenu(false);
        return;
      }
    }

    // Ctrl/Cmd+Enter to send
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="space-y-2">
    {(taskType === "ad_hoc" || taskType === "routine") && (
      <div className="relative rounded-lg border bg-card shadow-sm focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-1">
        {/* Input box + send button */}
        {/* Active command badge (overlaid on textarea) */}
        {activeCommand && (
          <div className="absolute top-2 left-3 z-10 pointer-events-none">
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium",
                "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
              )}
            >
              <activeCommand.icon className="h-3 w-3" />
              {activeCommand.command}
            </span>
          </div>
        )}

        {/* Slash command popover */}
        {showSlashMenu && filteredCommands.length > 0 && (
          <div
            ref={slashMenuRef}
            className="absolute bottom-full left-0 mb-1 w-80 rounded-lg border bg-popover p-1 shadow-lg z-50 max-h-96 overflow-y-auto"
          >
            {/* Group by System / Custom */}
            {["System", "Custom"].map((group) => {
              const groupCmds = filteredCommands.filter((c) => c.group === group);
              if (groupCmds.length === 0) return null;
              return (
                <div key={group}>
                  <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {group === "System" ? "🔧 System" : "📦 Custom"}
                  </div>
                  {groupCmds.map((cmd, idx) => {
                    const globalIdx = filteredCommands.indexOf(cmd);
                    return (
                      <button
                        key={cmd.skillId}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                          globalIdx === slashSelectedIndex
                            ? "bg-accent text-accent-foreground"
                            : "hover:bg-muted"
                        )}
                        onMouseEnter={() => setSlashSelectedIndex(globalIdx)}
                        onClick={() => selectSlashCommand(cmd)}
                      >
                        <cmd.icon className="h-4 w-4 text-muted-foreground shrink-0" />
                        <div className="text-left min-w-0 flex-1">
                          <div className="font-medium text-xs flex items-center gap-2">
                            {cmd.command}
                            {cmd.isActive && (
                              <span className="inline-block w-2 h-2 rounded-full bg-green-500" title="Active" />
                            )}
                          </div>
                          <div className="text-[11px] text-muted-foreground truncate">
                            {cmd.description}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}


        <Textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => handleTextChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            !currentTaskId
              ? "Select or create a task first"
              : taskType !== "ad_hoc" && !taskReady
              ? "Complete task setup before execution"
              : "Ask Owl to analyze your data… (type / for commands)"
          }
          disabled={!currentTaskId || isSending || (taskType === "routine" && !taskReady)}
          className={cn(
            "min-h-[80px] max-h-[160px] resize-none border-0 pr-14 focus-visible:ring-0 focus-visible:ring-offset-0",
            activeCommand && "pt-8" // push text down when badge is shown
          )}
          rows={3}
        />

        {/* Send / abort button */}
        {/* 发送/中止按钮：routine 用 handleExecute，ad_hoc 用 handleSend */}
        {isSending || isExecuting ? (
          <Button
            size="icon"
            variant="destructive"
            onClick={handleAbort}
            className="absolute bottom-2 right-2 h-8 w-8"
            title="Stop"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
          </Button>
        ) : (
          <Button
            size="icon"
            disabled={
              taskType === "ad_hoc"
                ? !text.trim() || !currentTaskId
                : !currentTaskId || !taskReady
            }
            onClick={taskType === "routine" ? handleExecute : handleSend}
            className="absolute bottom-2 right-2 h-8 w-8"
            title={taskType === "routine" ? "Run SOP" : "Send"}
          >
            <SendHorizonal className="h-4 w-4" />
          </Button>
        )}
      </div>
    )}
    {/* ── script / pipeline: 只显示执行按钮 ── */}
    {(taskType === "script" || taskType === "pipeline") && (
      <div className="flex items-center gap-3 rounded-lg border bg-card px-4 py-3 shadow-sm">
        <div className="flex-1 text-sm text-muted-foreground">
          {!taskReady
            ? "Complete task setup before execution"
            : taskType === "pipeline"
            ? "Run pipeline to update data"
            : "Replay script on bound data sources"}
        </div>
        {isExecuting ? (
          <Button variant="destructive" size="sm" onClick={handleAbort}>
            <Square className="mr-1.5 h-3.5 w-3.5 fill-current" />
            Stop
          </Button>
        ) : (
          <Button size="sm" onClick={handleExecute} disabled={!currentTaskId || !taskReady}>
            <FileCode2 className="mr-1.5 h-3.5 w-3.5" />
            Execute
          </Button>
        )}
      </div>
    )}
    {/* ── 底部控制栏 ── */}
    {/* ad_hoc: 完整的 mode + model 选择器 */}
    {/* routine: 只显示 model 选择器（mode 固定 analyst） */}
    {/* script/pipeline: 不显示 */}
    {(taskType === "ad_hoc" || taskType === "routine") && (
      <div className="flex items-center gap-2">
        {/* Context Ring */}
        <ContextRing />

        {taskType === "ad_hoc" && (
          <Select
            value={currentMode}
            onValueChange={(value: "auto" | "plan" | "analyst") =>
              setCurrentMode(value)
            }
            disabled={isSending}
          >
            <SelectTrigger className="h-7 w-[120px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">Auto</SelectItem>
              <SelectItem value="plan">Plan</SelectItem>
              <SelectItem value="analyst">Analyst</SelectItem>
            </SelectContent>
          </Select>
        )}

        {/* Model selector */}
        <Select
          value={
            selectedModel
              ? `${selectedModel.providerId}:${selectedModel.modelId}`
              : DEFAULT_MODEL_VALUE
          }
          onValueChange={(value) => {
            if (value === DEFAULT_MODEL_VALUE) {
              setSelectedModel(null);
              return;
            }
            const [providerId, modelId] = value.split(":");
            setSelectedModel({ providerId, modelId });
          }}
          disabled={isSending || availableModels.length === 0}
        >
          <SelectTrigger className="h-7 flex-1 text-xs">
            <SelectValue placeholder={getDisplayModel()} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={DEFAULT_MODEL_VALUE}>Use Default</SelectItem>
            {availableModels.map((model) => (
              <SelectItem key={model.value} value={model.value}>
                {model.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Shortcut hint */}
        <span className="ml-auto text-[10px] text-muted-foreground">
          {typeof navigator !== "undefined" &&
          /Mac|iPod|iPhone|iPad/.test(navigator.platform)
            ? "⌘"
            : "Ctrl"}
          +Enter
        </span>
      </div>
    )}
  </div>
);

}