// frontend/src/components/chat/message-input.tsx

"use client";

/**
 * 消息输入框 + 发送按钮 + Mode/Model 选择器
 * 支持用户切换执行模式（Auto/Plan/Analyst）和显式指定模型
 */
import * as React from "react";
import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SendHorizonal, Square } from "lucide-react";

import { streamChat, autoRenameTask } from "@/lib/api";
import type { SSEEvent } from "@/lib/api";
import { useTaskStore, Step } from "@/stores/use-task-store";
import { useSettingsStore } from "@/stores/use-settings-store";

// 特殊值，表示"使用默认配置"（避免空字符串导致 Radix UI 报错）
const DEFAULT_MODEL_VALUE = "__use_default__";

export default function MessageInput() {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const autoRenameCalledRef = useRef(false); 
  // 用于中止 SSE 流
  const abortControllerRef = useRef<AbortController | null>(null);

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
  } = useTaskStore();
  
  const { providers, agentConfigs } = useSettingsStore();

  // 构建可选模型列表（所有 Provider 的所有 Model）
  const availableModels = providers.flatMap((provider) =>
    provider.models.map((model) => ({
      value: `${provider.id}:${model.id}`,
      label: `${provider.display_name}/${model.name}`,
      providerId: provider.id,
      modelId: model.id,
    }))
  );

  /**
   * 获取当前模式的默认配置
   * 将前端的 mode 映射到后端的 agent_type
   */
  const getDefaultModelForMode = (mode: string) => {
    const agentTypeMap: Record<string, string> = {
      auto: "default",
      plan: "plan",
      analyst: "analyst",
    };
    
    const agentType = agentTypeMap[mode] || "default";
    const config = agentConfigs.find((c) => c.agent_type === agentType);
    
    if (!config || !config.provider_id || !config.model_id) return null;
    return {
      providerId: config.provider_id,
      modelId: config.model_id,
    };
  };

  /**
   * 获取显示的模型名称
   * 优先显示用户显式选择的模型，否则显示当前模式的默认配置
   */
  const getDisplayModel = () => {
    // 如果用户显式选择了模型，显示用户选择的
    if (selectedModel) {
      const found = availableModels.find(
        (m) => m.providerId === selectedModel.providerId && m.modelId === selectedModel.modelId
      );
      return found ? found.label : "Unknown";
    }
    
    // 否则显示当前模式的默认配置
    const defaultModel = getDefaultModelForMode(currentMode);
    if (!defaultModel) return "Not configured";
    
    const found = availableModels.find(
      (m) => m.providerId === defaultModel.providerId && m.modelId === defaultModel.modelId
    );
    return found ? found.label : "Unknown";
  };

  /* 自动调整 textarea 高度 */
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 160) + "px";
    }
  }, [text]);

  /** 中止当前 SSE 流 */
  const handleAbort = () => {
    try {
      abortControllerRef.current?.abort();
    } catch {
      // AbortError expected, ignore
    }
    abortControllerRef.current = null;
    clearStreaming();
    setPendingTool(currentTaskId!, null);
    setIsWaitingResponse(false);
    setIsSending(false);
  };

  const handleSend = async () => {
    if (!text.trim() || !currentTaskId || isSending) return;
    const message = text.trim();
    setText("");
    autoRenameCalledRef.current = false;
    setIsSending(true);
    setIsWaitingResponse(true); // 进入等待状态

    // 创建 AbortController 供中止使用
    const controller = new AbortController();
    abortControllerRef.current = controller;

    // 立即显示用户消息（临时，等 step_saved 替换）
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
      // 只有在用户显式选择模型时才传递 model_override
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
              // 收到首个实际内容，退出 waiting 状态
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
              // 收到 tool_start 也退出 waiting 状态
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
              // 代码执行完成（含捕获的 DataFrame 元数据）
              updatePendingToolResult(currentTaskId!, {
                success: event.success ?? false,
                output: event.output ?? null,
                error: event.error ?? null,
                time: event.time ?? 0,
                dataframes: event.dataframes,
              });
              break;

            case "step_saved": {
              // 一个 Step 已持久化 → 加入 steps 列表
              const step = event.step as unknown as Step;

              // 如果是 user_message，替换临时条目
              if (step.step_type === "user_message") {
                const store = useTaskStore.getState();
                const updatedSteps = store.steps.map((s) =>
                  s.id === tempUserId ? step : s
                );
                useTaskStore.setState({ steps: updatedSteps });
              } else {
                // 清除流式 / pending 状态，加入真实 Step
                clearStreaming();
                setPendingTool(currentTaskId!, null);
                addStep(step);
              }
              break;
            }

            case "visualization":
              // 当前版本以 step_saved(visualization) 为准，这里可忽略或用于将来做即时预览
              break;

            case "done": {
              // 全部完成 — 清除残留状态
              clearStreaming();
              setPendingTool(currentTaskId!, null);
              // 自动重命名：首次对话完成后，若 title 仍为默认模式则触发
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
        currentMode, // 传递mode
        modelOverride, // 只有显式选择时才传递
        controller // 传入外部 AbortController
      );
    } catch (err) {
      // AbortError 是用户主动中止，不需要报错
      if (err instanceof DOMException && err.name === "AbortError") {
        // 静默处理
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

  /** 清除当前流式文本状态（不创建临时 Step） */
  function _flushStreaming() {
    clearStreaming();
  }


  /* Ctrl/Cmd+Enter 发送，普通 Enter 换行 */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="space-y-2">
      {/* 输入框 + 发送按钮 */}
      <div className="relative rounded-lg border bg-card shadow-sm focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-1">
        <Textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            currentTaskId
              ? "Ask Owl to analyze your data..."
              : "Select or create a task first"
          }
          disabled={!currentTaskId || isSending}
          className="min-h-[80px] max-h-[160px] resize-none border-0 pr-14 focus-visible:ring-0 focus-visible:ring-offset-0"
          rows={3}
        />
        {/* 发送 / 中止按钮 */}
        {isSending ? (
          <Button
            size="icon"
            variant="destructive"
            onClick={handleAbort}
            className="absolute bottom-2 right-2 h-8 w-8"
            title="Stop generating"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
          </Button>
        ) : (
          <Button
            size="icon"
            disabled={!text.trim() || !currentTaskId}
            onClick={handleSend}
            className="absolute bottom-2 right-2 h-8 w-8"
          >
            <SendHorizonal className="h-4 w-4" />
          </Button>
        )}
      </div>

      {/* 模式选择器 + 模型选择器 + 快捷键提示 */}
      <div className="flex items-center gap-2">
        {/* 模式选择器 */}
        <Select
          value={currentMode}
          onValueChange={(value: "auto" | "plan" | "analyst") => setCurrentMode(value)}
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

        {/* 模型选择器 */}
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

        {/* 快捷键提示 */}
        <span className="ml-auto text-[10px] text-muted-foreground">
          {typeof navigator !== "undefined" &&
          /Mac|iPod|iPhone|iPad/.test(navigator.platform)
            ? "⌘"
            : "Ctrl"}
          +Enter to send
        </span>
      </div>
    </div>
  );
}