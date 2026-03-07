// frontend/src/components/chat/message-input.tsx

"use client";

/**
 * 消息输入框 + 发送按钮 + Mode/Model 占位
 */
import * as React from "react";
import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { useTaskStore } from "@/stores/use-task-store";
import { streamChat } from "@/lib/api";
import type { SSEEvent } from "@/lib/api";
import type { Step } from "@/stores/use-task-store";
import { SendHorizonal, Loader2 } from "lucide-react";

export default function MessageInput() {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const {
    currentTaskId,
    addStep,
    isSending,
    setIsSending,
    startStreaming,
    appendStreamingToken,
    clearStreaming,
    setPendingTool,
    updatePendingToolResult,
  } = useTaskStore();

  /* 自动调整 textarea 高度 */
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 160) + "px";
    }
  }, [text]);

  const handleSend = async () => {
    if (!text.trim() || !currentTaskId || isSending) return;
    const message = text.trim();
    setText("");
    setIsSending(true);

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
      await streamChat(currentTaskId, message, (event: SSEEvent) => {
        switch (event.type) {
          case "text":
            // 流式文本 → 追加到 streamingMessage
            if (!useTaskStore.getState().streamingMessage) {
              startStreaming();
            }
            if (event.content) {
              appendStreamingToken(event.content);
            }
            break;

          case "tool_start":
            // 代码即将执行 → 先把当前流式文本冲刷掉
            _flushStreaming();
            setPendingTool({
              code: event.code || "",
              purpose: event.purpose || "",
              status: "running",
            });
            break;

          case "tool_result":
            // 代码执行完成（含捕获的 DataFrame 元数据）
            updatePendingToolResult({
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
              setPendingTool(null);
              addStep(step);
            }
            break;
          }

          case "done": {
            // 全部完成 — 冲刷可能残留的流式文本
            const finalState = useTaskStore.getState();
            if (
              finalState.streamingMessage &&
              finalState.streamingMessage.content.trim()
            ) {
              addStep({
                id: `stream-flush-${Date.now()}`,
                task_id: currentTaskId!,
                role: "assistant",
                step_type: "assistant_message",
                content: finalState.streamingMessage.content.trim(),
                code: null,
                code_output: null,
                created_at: new Date().toISOString(),
              });
            }
            clearStreaming();
            setPendingTool(null);
            break;
          }


          case "error":
            clearStreaming();
            setPendingTool(null);
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
      });
    } catch (err) {
      console.error("Stream failed:", err);
      clearStreaming();
      setPendingTool(null);
      addStep({
        id: `error-${Date.now()}`,
        task_id: currentTaskId,
        role: "assistant",
        step_type: "assistant_message",
        content: "⚠️ 网络请求失败，请检查后端是否正常运行。",
        code: null,
        code_output: null,
        created_at: new Date().toISOString(),
      });
    } finally {
      setIsSending(false);
    }
  };

  /** 将当前 streamingMessage 内容冲刷为临时 Step */
  function _flushStreaming() {
    const store = useTaskStore.getState();
    if (store.streamingMessage && store.streamingMessage.content.trim()) {
      // 不主动添加临时 step，等 step_saved 事件
      // 只清除 streaming 状态
    }
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
        <Button
          size="icon"
          disabled={!text.trim() || !currentTaskId || isSending}
          onClick={handleSend}
          className="absolute bottom-2 right-2 h-8 w-8"
        >
          {isSending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <SendHorizonal className="h-4 w-4" />
          )}
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <Badge variant="outline" className="cursor-pointer text-xs hover:bg-accent">
          Mode: Auto
        </Badge>
        <Badge variant="outline" className="cursor-pointer text-xs hover:bg-accent">
          Model: GPT-4o
        </Badge>
        {/* 发送快捷键提示 */}
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