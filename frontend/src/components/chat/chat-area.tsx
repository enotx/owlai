// frontend/src/components/chat/chat-area.tsx

"use client";

/**
 * 中栏：Knowledge Zone + 对话消息列表 + 输入框
 */
import { useEffect, useRef } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useTaskStore } from "@/stores/use-task-store";
import KnowledgeZone from "./knowledge-zone";
import MessageInput from "./message-input";
import { Bot, User } from "lucide-react";
import { cn } from "@/lib/utils";

export default function ChatArea() {
  const { currentTaskId, steps } = useTaskStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  /* 新消息到达时自动滚动到底部 */
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [steps]);

  return (
    <div className="flex h-full flex-col">
      {/* 顶部：Knowledge Zone */}
      <div className="shrink-0 border-b px-4 py-3">
        {currentTaskId ? (
          <KnowledgeZone />
        ) : (
          <div className="rounded-lg border border-dashed bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">
            Select or create a task to start
          </div>
        )}
      </div>

      {/* 中间：消息列表 */}
      <ScrollArea className="flex-1 px-4">
        <div className="mx-auto max-w-2xl space-y-4 py-4">
          {steps.length === 0 && currentTaskId && (
            <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
              <Bot className="mb-3 h-10 w-10 opacity-30" />
              <p className="text-sm">Upload data and start asking questions</p>
            </div>
          )}
          {steps.map((step) => (
            <div
              key={step.id}
              className={cn(
                "flex gap-3",
                step.role === "user" ? "justify-end" : "justify-start"
              )}
            >
              {/* AI 头像 */}
              {step.role === "assistant" && (
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                  <Bot className="h-4 w-4" />
                </div>
              )}

              {/* 消息气泡 */}
              <div
                className={cn(
                  "max-w-[80%] rounded-lg px-3.5 py-2.5 text-sm leading-relaxed",
                  step.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted"
                )}
              >
                <p className="whitespace-pre-wrap">{step.content}</p>
                {/* 如果有代码则展示 */}
                {step.code && (
                  <pre className="mt-2 overflow-x-auto rounded bg-black/80 p-2 text-xs text-green-400">
                    <code>{step.code}</code>
                  </pre>
                )}
                {step.code_output && (
                  <pre className="mt-1 overflow-x-auto rounded bg-muted-foreground/10 p-2 text-xs">
                    <code>{step.code_output}</code>
                  </pre>
                )}
              </div>

              {/* 用户头像 */}
              {step.role === "user" && (
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary">
                  <User className="h-4 w-4" />
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {/* 底部：输入框 */}
      <div className="shrink-0 border-t px-4 py-3">
        <div className="mx-auto max-w-2xl">
          <MessageInput />
        </div>
      </div>
    </div>
  );
}