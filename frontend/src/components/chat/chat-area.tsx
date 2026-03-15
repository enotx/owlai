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
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { CapturedDataFrame } from "@/stores/use-task-store";



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
  const { currentTaskId, steps, streamingMessage, pendingTool } = useTaskStore();
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
  }, [steps, streamingMessage, pendingTool]);


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

          {/* 已持久化的 Steps */}
          {steps.map((step) => {
            if (step.step_type === "user_message") {
              return <UserBubble key={step.id} step={step} />;
            }
            if (step.step_type === "tool_use") {
              return <ToolUseBlock key={step.id} step={step} />;
            }
            if (step.step_type === "visualization") {
              return <VisualizationBlock key={step.id} step={step} />;
            }
            return <AssistantBubble key={step.id} content={step.content} />;
          })}

          {/* 正在执行的代码（pending） */}
          {pendingTool && <PendingToolBlock tool={pendingTool} />}

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