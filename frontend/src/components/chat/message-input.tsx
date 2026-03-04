// frontend/src/components/chat/message-input.tsx

"use client";

/**
 * 消息输入框 + 发送按钮 + Mode/Model 切换（占位）
 */
import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { useTaskStore } from "@/stores/use-task-store";
import { sendMessage } from "@/lib/api";
import { SendHorizonal, Loader2 } from "lucide-react";

export default function MessageInput() {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { currentTaskId, addStep, isSending, setIsSending } = useTaskStore();

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

    // 立即将用户消息添加到界面
    addStep({
      id: `temp-${Date.now()}`,
      task_id: currentTaskId,
      role: "user",
      content: message,
      code: null,
      code_output: null,
      created_at: new Date().toISOString(),
    });

    setIsSending(true);
    try {
      const res = await sendMessage(currentTaskId, message);
      addStep(res.data);
    } catch (err) {
      console.error("Send failed:", err);
      addStep({
        id: `error-${Date.now()}`,
        task_id: currentTaskId,
        role: "assistant",
        content: "⚠️ 请求失败，请稍后重试。",
        code: null,
        code_output: null,
        created_at: new Date().toISOString(),
      });
    } finally {
      setIsSending(false);
    }
  };

  /* Enter 发送，Shift+Enter 换行 */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="space-y-2">
      {/* 输入区域 */}
      <div className="relative rounded-lg border bg-card shadow-sm focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-1">
        <Textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={currentTaskId ? "Ask Owl to analyze your data..." : "Select or create a task first"}
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

      {/* Mode / Model 占位标签 */}
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="cursor-pointer text-xs hover:bg-accent">
          Mode: Auto
        </Badge>
        <Badge variant="outline" className="cursor-pointer text-xs hover:bg-accent">
          Model: GPT-4o
        </Badge>
      </div>
    </div>
  );
}