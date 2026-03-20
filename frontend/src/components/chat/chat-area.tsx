// frontend/src/components/chat/chat-area.tsx

"use client";

/**
 * 中栏：Knowledge Zone + 对话消息列表 + 输入框
 * 支持渲染 user_message / assistant_message / tool_use + 流式消息 + pending tool
 */
import { useEffect, useRef, useMemo, useCallback, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useTaskStore } from "@/stores/use-task-store";
import type { Step, PendingToolExecution, StreamingMessage } from "@/stores/use-task-store";
import KnowledgeZone from "./knowledge-zone";
import MessageInput from "./message-input";
import SubTaskList from "./subtask-list";
import PlanConfirmationDialog from "./plan-confirmation";
import EChartsView from "./echarts-view";



import {
  Bot,
  User,
  Code2,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  Database,
  ChevronDown,
  ChevronRight,
  Trash2,
  RotateCcw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { CapturedDataFrame } from "@/stores/use-task-store";
import { deleteStepAndAfter, regenerateFromStep, fetchChatHistory, streamChat } from "@/lib/api";
import type { SSEEvent } from "@/lib/api";


// ── 单条用户消息 ──────────────────────────────────────────────
function UserBubble({ step }: { step: Step }) {
  return (
    <div className="flex gap-3 justify-end">
      <div className="max-w-[80%] rounded-lg bg-primary px-3.5 py-2.5 text-sm leading-relaxed text-primary-foreground">
        <p className="whitespace-pre-wrap">{step.content}</p>
      </div>
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary">
        <User className="h-4 w-4" />
      </div>
    </div>
  );
}

// ── 单条 assistant 文本消息 ───────────────────────────────────
function AssistantBubble({ content }: { content: string }) {
  return (
    <div className="flex gap-3 justify-start">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
        <Bot className="h-4 w-4" />
      </div>
      <div className="max-w-[80%] rounded-lg bg-muted px-3.5 py-2.5 text-sm leading-relaxed">
        <p className="whitespace-pre-wrap">{content}</p>
      </div>
    </div>
  );
}

// ── 代码执行块（tool_use Step）- 支持折叠/展开 ───────────────
function ToolUseBlock({ step }: { step: Step }) {
  // 默认折叠代码块
  const [isCodeExpanded, setIsCodeExpanded] = useState(false);

  const parsed = useMemo(() => {
    if (!step.code_output) return null;
    try {
      return JSON.parse(step.code_output) as {
        success: boolean;
        output: string | null;
        error: string | null;
        execution_time: number;
        dataframes?: CapturedDataFrame[];
      };
    } catch {
      return null;
    }
  }, [step.code_output]);

  return (
    <div className="flex gap-3 justify-start">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-500 text-white">
        <Code2 className="h-4 w-4" />
      </div>
      <div className="max-w-[85%] w-full space-y-2">
        {/* 目的说明 */}
        {step.content && (
          <p className="text-xs text-muted-foreground italic">
            📌 {step.content}
          </p>
        )}
        
        {/* 代码块 - 可折叠 */}
        {step.code && (
          <div className="space-y-1">
            <button
              onClick={() => setIsCodeExpanded(!isCodeExpanded)}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              {isCodeExpanded ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
              <span>{isCodeExpanded ? "Hide code" : "Show code"}</span>
            </button>
            {isCodeExpanded && (
              <pre className="overflow-x-auto rounded-md bg-zinc-900 p-3 text-xs text-green-400 leading-relaxed">
                <code>{step.code}</code>
              </pre>
            )}
          </div>
        )}

        {/* 执行结果 - 永远展示 */}
        {parsed && (
          <div
            className={cn(
              "rounded-md border p-3 text-xs",
              parsed.success
                ? "border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950"
                : "border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-950"
            )}
          >
            <div className="mb-1 flex items-center gap-1.5">
              {parsed.success ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
              ) : (
                <XCircle className="h-3.5 w-3.5 text-red-600" />
              )}
              <span className="font-medium">
                {parsed.success ? "Execution succeeded" : "Execution failed"}
              </span>
              <span className="ml-auto text-muted-foreground flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {parsed.execution_time.toFixed(2)}s
              </span>
            </div>
            {parsed.output && (
              <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words text-foreground">
                {parsed.output}
              </pre>
            )}
            {parsed.error && (
              <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words text-red-600 dark:text-red-400">
                {parsed.error}
              </pre>
            )}
            {/* 捕获的 DataFrame 预览链接 */}
            {parsed.dataframes && parsed.dataframes.length > 0 && (
              <DataFrameLinks dataframes={parsed.dataframes} stepId={step.id} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function VisualizationBlock({ step }: { step: Step }) {
  const parsed = useMemo(() => {
    if (!step.code_output) return null;
    try {
      return JSON.parse(step.code_output) as {
        visualization_id: string;
        title: string;
        chart_type: string;
        option: Record<string, unknown>;
      };
    } catch {
      return null;
    }
  }, [step.code_output]);

  if (!parsed?.option) {
    return (
      <div className="flex gap-3 justify-start">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Bot className="h-4 w-4" />
        </div>
        <div className="max-w-[85%] w-full rounded-lg bg-muted px-3.5 py-2.5 text-sm">
          <p className="whitespace-pre-wrap">{step.content}</p>
          <p className="mt-2 text-xs text-muted-foreground">Invalid chart payload.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 justify-start">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
        <Bot className="h-4 w-4" />
      </div>
      <div className="max-w-[85%] w-full space-y-2">
        <div className="rounded-lg bg-muted px-3.5 py-2.5 text-sm">
          <p className="font-medium">📊 {parsed.title || step.content}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Chart type: {parsed.chart_type}
          </p>
        </div>

        <EChartsView option={parsed.option} height={360} />
      </div>
    </div>
  );
}


// ── 流式消息（正在打字） ──────────────────────────────────────
function StreamingBubble({ message }: { message: StreamingMessage }) {
  return (
    <div className="flex gap-3 justify-start">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
        <Bot className="h-4 w-4" />
      </div>
      <div className="max-w-[80%] rounded-lg bg-muted px-3.5 py-2.5 text-sm leading-relaxed">
        <p className="whitespace-pre-wrap">
          {message.content}
          <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-foreground/60" />
        </p>
      </div>
    </div>
  );
}

// ── 等待LLM首次响应的占位块 ──────────────────────────────────
function WaitingBubble() {
  return (
    <div className="flex gap-3 justify-start">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
        <Bot className="h-4 w-4" />
      </div>
      <div className="max-w-[80%] rounded-lg bg-muted px-3.5 py-2.5 text-sm leading-relaxed">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          <span>Waiting for the response...</span>
        </div>
      </div>
    </div>
  );
}

// ── Step 操作按钮（删除 / 重新生成）─────────────────────────
function StepActions({
  step,
  onRegenerate,
}: {
  step: Step;
  onRegenerate?: (userMessage: string, taskId: string) => void;
}) {
  const { removeStepsByIds, isSending } = useTaskStore();
  const [isDeleting, setIsDeleting] = useState(false);

  // 发送中时不显示操作按钮
  if (isSending) return null;

  const handleDelete = async () => {
    if (isDeleting) return;
    setIsDeleting(true);
    try {
      const res = await deleteStepAndAfter(step.id);
      const deletedIds: string[] = res.data.deleted_ids;
      if (deletedIds.length > 0) {
        // 从 store 中移除被删除的 steps
        removeStepsByIds(deletedIds);
      }
    } catch (err) {
      console.error("Delete step failed:", err);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleRegenerate = async () => {
    if (isDeleting) return;
    setIsDeleting(true);
    try {
      const res = await regenerateFromStep(step.id);
      const { user_message, task_id, deleted_ids } = res.data;
      if (deleted_ids.length > 0) {
        removeStepsByIds(deleted_ids);
      }
      // 触发重新发送
      if (user_message && onRegenerate) {
        onRegenerate(user_message, task_id);
      }
    } catch (err) {
      console.error("Regenerate failed:", err);
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      {/* 只有 assistant 消息和 tool_use 才显示重新生成 */}
      {(step.step_type === "assistant_message" || step.step_type === "tool_use" || step.step_type === "visualization") && (
        <button
          onClick={handleRegenerate}
          disabled={isDeleting}
          className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
          title="Regenerate from here"
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
      )}
      <button
        onClick={handleDelete}
        disabled={isDeleting}
        className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
        title="Delete this and all following steps"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ── DataFrame 预览链接列表 ────────────────────────────────
function DataFrameLinks({
  dataframes,
  stepId,
}: {
  dataframes: CapturedDataFrame[];
  stepId?: string;
}) {
  const { loadStepDataframe } = useTaskStore();
  if (!dataframes || dataframes.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {dataframes.map((df) => (
        <button
          key={`${df.capture_id}-${df.name}`}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5",
            "text-xs font-medium transition-colors",
            "border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100",
            "dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300 dark:hover:bg-blue-900",
            "cursor-pointer"
          )}
          onClick={() => {
            if (stepId) {
              loadStepDataframe(stepId, df.name);
            }
          }}
        >
          <Database className="h-3 w-3" />
          <span>
            {df.name}
          </span>
          <span className="text-blue-500 dark:text-blue-400">
            ({df.row_count.toLocaleString()} rows × {df.columns.length} cols)
          </span>
        </button>
      ))}
    </div>
  );
}


// ── 代码执行中占位（pending tool） ────────────────────────────
function PendingToolBlock({ tool }: { tool: PendingToolExecution }) {
  return (
    <div className="flex gap-3 justify-start">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-500 text-white">
        <Code2 className="h-4 w-4" />
      </div>
      <div className="max-w-[85%] w-full space-y-2">
        {tool.purpose && (
          <p className="text-xs text-muted-foreground italic">
            📌 {tool.purpose}
          </p>
        )}
        <pre className="overflow-x-auto rounded-md bg-zinc-900 p-3 text-xs text-green-400 leading-relaxed">
          <code>{tool.code}</code>
        </pre>
        {tool.status === "running" && (
          <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs dark:border-amber-800 dark:bg-amber-950">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-600" />
            <span className="text-amber-700 dark:text-amber-400">
              Executing code...
            </span>
          </div>
        )}
        {tool.status === "done" && tool.result && (
          <div
            className={cn(
              "rounded-md border p-3 text-xs",
              tool.result.success
                ? "border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-950"
                : "border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-950"
            )}
          >
            <div className="mb-1 flex items-center gap-1.5">
              {tool.result.success ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
              ) : (
                <XCircle className="h-3.5 w-3.5 text-red-600" />
              )}
              <span className="font-medium">
                {tool.result.success ? "Execution succeeded" : "Execution failed"}
              </span>
              <span className="ml-auto text-muted-foreground flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {tool.result.time.toFixed(2)}s
              </span>
            </div>
            {tool.result.output && (
              <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words text-foreground">
                {tool.result.output}
              </pre>
            )}
            {tool.result.error && (
              <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words text-red-600 dark:text-red-400">
                {tool.result.error}
              </pre>
            )}
            {/* 捕获的 DataFrame 预览链接（pending 状态下无 stepId，暂不可点） */}
            {tool.result.dataframes && tool.result.dataframes.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {tool.result.dataframes.map((df) => (
                  <div
                    key={`${df.capture_id}-${df.name}`}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5",
                      "text-xs font-medium",
                      "border-blue-200 bg-blue-50 text-blue-700",
                      "dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300",
                      "opacity-60"
                    )}
                  >
                    <Database className="h-3 w-3" />
                    <span>{df.name}</span>
                    <span className="text-blue-500 dark:text-blue-400">
                      ({df.row_count.toLocaleString()} rows × {df.columns.length} cols)
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── 主组件 ────────────────────────────────────────────────────
export default function ChatArea() {
  const {
    currentTaskId,
    steps,
    streamingMessage,
    pendingTool,
    isWaitingResponse,
    isSending,
    setIsSending,
    setIsWaitingResponse,
    addStep,
    startStreaming,
    appendStreamingToken,
    clearStreaming,
    setPendingTool,
    updatePendingToolResult,
    currentMode,
    selectedModel,
  } = useTaskStore();
  const bottomRef = useRef<HTMLDivElement>(null);
  /** 滚动容器引用（ScrollArea 内部的 viewport） */
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  /** 用户是否处于底部附近，是则自动跟随新消息滚动 */
  const isNearBottomRef = useRef(true);
  /** 判断是否接近底部（阈值 80px） */
  const checkIfNearBottom = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }, []);
  /** 重新生成：接收用户消息后自动重发 */
  const handleRegenerate = useCallback(async (userMessage: string, taskId: string) => {
    if (isSending) return;
    setIsSending(true);
    setIsWaitingResponse(true);
    // 添加临时用户消息
    const tempUserId = `temp-user-${Date.now()}`;
    addStep({
      id: tempUserId,
      task_id: taskId,
      role: "user",
      step_type: "user_message",
      content: userMessage,
      code: null,
      code_output: null,
      created_at: new Date().toISOString(),
    });
    try {
      const modelOverride = selectedModel
        ? { provider_id: selectedModel.providerId, model_id: selectedModel.modelId }
        : undefined;
      await streamChat(
        taskId,
        userMessage,
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
              setPendingTool({
                code: event.code || "",
                purpose: event.purpose || "",
                status: "running",
              });
              break;
            case "tool_result":
              updatePendingToolResult({
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
                useTaskStore.setState({
                  steps: store.steps.map((s) => (s.id === tempUserId ? step : s)),
                });
              } else {
                clearStreaming();
                setPendingTool(null);
                addStep(step);
              }
              break;
            }
            case "done":
              clearStreaming();
              setPendingTool(null);
              setIsWaitingResponse(false);
              break;
            case "error":
              clearStreaming();
              setPendingTool(null);
              setIsWaitingResponse(false);
              addStep({
                id: `error-${Date.now()}`,
                task_id: taskId,
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
        modelOverride
      );
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        console.error("Regenerate stream failed:", err);
        addStep({
          id: `error-${Date.now()}`,
          task_id: taskId,
          role: "assistant",
          step_type: "assistant_message",
          content: "⚠️ 网络请求失败,请检查后端是否正常运行。",
          code: null,
          code_output: null,
          created_at: new Date().toISOString(),
        });
      }
    } finally {
      setIsSending(false);
      setIsWaitingResponse(false);
    }
  }, [isSending, currentMode, selectedModel, setIsSending, setIsWaitingResponse, addStep, startStreaming, appendStreamingToken, clearStreaming, setPendingTool, updatePendingToolResult]);
  /** 监听滚动事件，更新 isNearBottom 标志 */
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const onScroll = () => {
      isNearBottomRef.current = checkIfNearBottom();
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [checkIfNearBottom]);
  /* 新消息/流式更新时，仅在用户处于底部附近时自动滚动 */
  useEffect(() => {
    if (isNearBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [steps, streamingMessage, pendingTool, isWaitingResponse]);


  return (
    <div className="flex h-full flex-col">
      {/* 顶部：Knowledge Zone */}
      <div className="shrink-0 border-b px-4 py-3">
        {currentTaskId ? (
          <>
            <KnowledgeZone />
            {/* SubTask列表 */}
            <div className="mt-3">
              <SubTaskList />
            </div>
          </>
        ) : (
          <div className="rounded-lg border border-dashed bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">
            Select or create a task to start
          </div>
        )}
      </div>

      {/* 中间：消息列表，支持鼠标滚轮浏览历史 */}
      <ScrollArea
        className="flex-1 min-h-0 px-4"
        ref={(node) => {
          // 获取 Radix ScrollArea 内部的实际可滚动 viewport
          if (node) {
            const viewport = (node as HTMLElement).querySelector(
              "[data-radix-scroll-area-viewport]"
            ) as HTMLDivElement | null;
            scrollContainerRef.current = viewport;
          }
        }}
      >
        <div className="mx-auto max-w-2xl space-y-4 py-4">
          {/* 空状态 */}
          {steps.length === 0 && currentTaskId && !streamingMessage && (
            <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
              <Bot className="mb-3 h-10 w-10 opacity-30" />
              <p className="text-sm">Upload data and start asking questions</p>
            </div>
          )}

          {/* 已持久化的 Steps — 带操作按钮 */}
          {steps.map((step) => {
            // 临时 step（temp-user-* / error-*）不显示操作按钮
            const isTemp = step.id.startsWith("temp-") || step.id.startsWith("error-");

            if (step.step_type === "user_message") {
              return (
                <div key={step.id} className="group relative">
                  <UserBubble step={step} />
                  {!isTemp && (
                    <div className="absolute -bottom-1 right-10">
                      <StepActions step={step} onRegenerate={handleRegenerate} />
                    </div>
                  )}
                </div>
              );
            }
            if (step.step_type === "tool_use") {
              return (
                <div key={step.id} className="group relative">
                  <ToolUseBlock step={step} />
                  {!isTemp && (
                    <div className="absolute -bottom-1 left-10">
                      <StepActions step={step} onRegenerate={handleRegenerate} />
                    </div>
                  )}
                </div>
              );
            }
            if (step.step_type === "visualization") {
              return (
                <div key={step.id} className="group relative">
                  <VisualizationBlock step={step} />
                  {!isTemp && (
                    <div className="absolute -bottom-1 left-10">
                      <StepActions step={step} onRegenerate={handleRegenerate} />
                    </div>
                  )}
                </div>
              );
            }
            return (
              <div key={step.id} className="group relative">
                <AssistantBubble content={step.content} />
                {!isTemp && (
                  <div className="absolute -bottom-1 left-10">
                    <StepActions step={step} onRegenerate={handleRegenerate} />
                  </div>
                )}
              </div>
            );
          })}

          {/* 正在执行的代码（pending） */}
          {pendingTool && <PendingToolBlock tool={pendingTool} />}

          {/* 等待LLM首次响应的占位 */}
          {isWaitingResponse && !streamingMessage && !pendingTool && (
            <WaitingBubble />
          )}

          {/* 流式打字中 */}
          {streamingMessage && streamingMessage.content && (
            <StreamingBubble message={streamingMessage} />
          )}
          
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {/* 底部：输入框 */}
      <div className="shrink-0 border-t px-4 py-3">
        <div className="mx-auto max-w-2xl">
          <MessageInput />
        </div>
      </div>

      {/* Plan确认对话框 */}
      <PlanConfirmationDialog />

    </div>
  );
}