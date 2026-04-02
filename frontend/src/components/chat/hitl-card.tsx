// frontend/src/components/chat/hitl-card.tsx

"use client";

/**
 * HITL (Human-in-the-Loop) 决策卡片
 * 显示选项供用户选择，最后一个永远是自由输入
 */
import { useState, useRef } from "react";
import { Bot, ShieldQuestion, Send, Code2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { HITLOption } from "@/stores/use-task-store";

interface HITLCardProps {
  title: string;
  description: string;
  options: HITLOption[];
  /** 是否已提交（历史记录中已回复则为 true） */
  resolved: boolean;
  /** 用户选择后的回调 */
  onSubmit?: (choice: { type: "option" | "custom"; value: string; label: string }) => void;
}

export default function HITLCard({
  title,
  description,
  options,
  resolved,
  onSubmit,
}: HITLCardProps) {
  const [selectedValue, setSelectedValue] = useState<string | null>(null);
  const [customText, setCustomText] = useState("");
  const [isCustom, setIsCustom] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const customInputRef = useRef<HTMLTextAreaElement>(null);

  const handleOptionClick = (value: string) => {
    if (resolved || isSubmitting) return;
    setSelectedValue(value);
    setIsCustom(false);
  };

  const handleCustomFocus = () => {
    if (resolved || isSubmitting) return;
    setSelectedValue(null);
    setIsCustom(true);
  };

  const handleSubmit = () => {
    if (resolved || isSubmitting || !onSubmit) return;

    if (isCustom) {
      if (!customText.trim()) return;
      setIsSubmitting(true);
      onSubmit({
        type: "custom",
        value: customText.trim(),
        label: customText.trim(),
      });
    } else if (selectedValue) {
      const opt = options.find((o) => o.value === selectedValue);
      setIsSubmitting(true);
      onSubmit({
        type: "option",
        value: selectedValue,
        label: opt?.label || selectedValue,
      });
    }
  };

  const canSubmit = !resolved && !isSubmitting && (selectedValue !== null || (isCustom && customText.trim().length > 0));

  return (
    <div className="flex gap-3 justify-start">
      {/* Avatar */}
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
        <Bot className="h-4 w-4" />
      </div>

      <div className="max-w-[85%] w-full space-y-2">
        {/* Description text */}
        {description && (
          <div className="rounded-lg bg-muted px-3.5 py-2.5 text-sm leading-relaxed">
            {description}
          </div>
        )}

        {/* Card */}
        <div
          className={cn(
            "rounded-xl border-2 bg-card shadow-sm overflow-hidden",
            resolved
              ? "border-muted opacity-75"
              : "border-primary/20"
          )}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
            <div className="flex items-center gap-2 text-sm font-semibold text-primary">
              <ShieldQuestion className="h-4 w-4" />
              <span>AWAITING YOUR GUIDANCE</span>
            </div>
            <span className="text-xs text-muted-foreground">{title}</span>
          </div>

          {/* Options */}
          <div className="p-4 space-y-2">
            {options.map((option) => (
              <button
                key={option.value}
                onClick={() => handleOptionClick(option.value)}
                disabled={resolved || isSubmitting}
                className={cn(
                  "w-full flex items-center justify-between rounded-lg border px-4 py-3 text-sm transition-all text-left",
                  resolved || isSubmitting
                    ? "cursor-not-allowed opacity-60"
                    : "cursor-pointer hover:border-primary/50 hover:bg-muted/50",
                  selectedValue === option.value && !resolved
                    ? "border-primary bg-primary/5 ring-1 ring-primary/30"
                    : "border-border"
                )}
              >
                <div className="flex items-center gap-3">
                  {/* Radio indicator */}
                  <div
                    className={cn(
                      "h-4 w-4 rounded-full border-2 flex items-center justify-center shrink-0",
                      selectedValue === option.value
                        ? "border-primary"
                        : "border-muted-foreground/40"
                    )}
                  >
                    {selectedValue === option.value && (
                      <div className="h-2 w-2 rounded-full bg-primary" />
                    )}
                  </div>
                  <span>{option.label}</span>
                </div>
                {option.badge && (
                  <span
                    className={cn(
                      "ml-2 shrink-0 rounded-md px-2 py-0.5 text-xs font-mono",
                      option.badge.startsWith("-")
                        ? "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400"
                        : "bg-muted text-muted-foreground"
                    )}
                  >
                    {option.badge}
                  </span>
                )}
              </button>
            ))}

            {/* Custom input */}
            <div className="mt-3">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                Other (type your own logic...)
              </div>
              <div
                className={cn(
                  "relative rounded-lg border transition-all",
                  isCustom && !resolved
                    ? "border-primary ring-1 ring-primary/30"
                    : "border-border",
                  resolved || isSubmitting ? "opacity-60" : ""
                )}
              >
                <textarea
                  ref={customInputRef}
                  value={customText}
                  onChange={(e) => setCustomText(e.target.value)}
                  onFocus={handleCustomFocus}
                  disabled={resolved || isSubmitting}
                  placeholder="e.g., fill with 0"
                  rows={1}
                  className={cn(
                    "w-full resize-none bg-transparent px-3 py-2.5 text-sm",
                    "placeholder:text-muted-foreground/50",
                    "focus:outline-none",
                    "disabled:cursor-not-allowed"
                  )}
                />
                <Code2 className="absolute right-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/40" />
              </div>
            </div>
          </div>

          {/* Submit button */}
          {!resolved && (
            <div className="px-4 pb-4 pt-1">
              <button
                onClick={handleSubmit}
                disabled={!canSubmit}
                className={cn(
                  "w-full flex items-center justify-center gap-2 rounded-lg px-4 py-2.5",
                  "text-sm font-semibold transition-all",
                  canSubmit
                    ? "bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer"
                    : "bg-muted text-muted-foreground cursor-not-allowed"
                )}
              >
                {isSubmitting ? (
                  <>Processing...</>
                ) : (
                  <>
                    Confirm & Proceed
                    <Send className="h-3.5 w-3.5" />
                  </>
                )}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}