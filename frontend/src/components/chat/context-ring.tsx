// frontend/src/components/chat/context-ring.tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { useTaskStore } from "@/stores/use-task-store";
import { startCompact, getCompactStatus } from "@/lib/api";
import { Loader2, Zap, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

const MAX_TOKENS = 100_000;
const POLL_INTERVAL = 5000; // 5秒轮询一次

export default function ContextRing() {
  const {
    currentTaskId,
    contextTokens,
    contextLoading,
    needsCompact,
    refreshContextSize,
    isSending,
    steps,
    knowledgeList,
    currentMode,
  } = useTaskStore();

  const [showMenu, setShowMenu] = useState(false);
  const [compacting, setCompacting] = useState(false);
  const [compactProgress, setCompactProgress] = useState(0);
  const [compactPhase, setCompactPhase] = useState("");
  const [compactResult, setCompactResult] = useState<{
    show: boolean;
    success: boolean;
    message: string;
  } | null>(null);
  
  const menuRef = useRef<HTMLDivElement>(null);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);

  // 计算进度百分比
  const percentage = Math.min((contextTokens / MAX_TOKENS) * 100, 100);
  const radius = 14;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (percentage / 100) * circumference;

  // 颜色：< 70% 绿色，70-90% 黄色，> 90% 红色
  const color =
    percentage < 70
      ? "#10b981"
      : percentage < 90
      ? "#f59e0b"
      : "#ef4444";

  // 初始加载 + 依赖变化时刷新
  useEffect(() => {
    if (currentTaskId && !contextLoading) {
      refreshContextSize();
    }
  }, [currentTaskId, steps.length, knowledgeList.length, currentMode]);

  // 点击外部关闭菜单
  useEffect(() => {
    if (!showMenu) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowMenu(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showMenu]);

  // 自动隐藏结果提示
  useEffect(() => {
    if (compactResult?.show) {
      const timer = setTimeout(() => {
        setCompactResult(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [compactResult]);

  // 清理轮询定时器
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, []);

  // 轮询压缩状态
  const pollCompactStatus = async () => {
    if (!currentTaskId) return;

    try {
      const res = await getCompactStatus(currentTaskId);
      const status = res.data;

      if (status.status === "running") {
        setCompactProgress(status.progress);
        setCompactPhase(status.message);
        
        // 继续轮询
        pollTimerRef.current = setTimeout(pollCompactStatus, POLL_INTERVAL);
      } else if (status.status === "completed") {
        setCompacting(false);
        setCompactProgress(100);
        
        // 刷新 context size
        await refreshContextSize();

        // 显示成功提示
        const result = status.result!;
        const message = result.warning
          ? `⚠️ ${result.warning}`
          : `✓ Compressed ${(result.original_tokens / 1000).toFixed(1)}K → ${(result.compressed_tokens / 1000).toFixed(1)}K tokens (${Math.round(result.compression_ratio * 100)}%)`;

        setCompactResult({
          show: true,
          success: !result.warning,
          message,
        });
      } else if (status.status === "failed") {
        setCompacting(false);
        setCompactProgress(0);
        
        setCompactResult({
          show: true,
          success: false,
          message: `✗ Compression failed: ${status.error || status.message}`,
        });
      }
    } catch (err: any) {
      console.error("Poll compact status failed:", err);
      setCompacting(false);
      setCompactProgress(0);
      
      setCompactResult({
        show: true,
        success: false,
        message: `✗ Status check failed: ${err.message}`,
      });
    }
  };

  const handleCompact = async () => {
    if (!currentTaskId || compacting || isSending) return;
    setShowMenu(false);
    setCompacting(true);
    setCompactProgress(0);
    setCompactPhase("Starting...");

    try {
      // 启动后台任务
      await startCompact(currentTaskId);
      
      // 开始轮询
      pollTimerRef.current = setTimeout(pollCompactStatus, POLL_INTERVAL);
    } catch (err: any) {
      console.error("Start compact failed:", err);
      setCompacting(false);
      setCompactProgress(0);
      
      setCompactResult({
        show: true,
        success: false,
        message: `✗ Failed to start compression: ${err.response?.data?.detail || err.message}`,
      });
    }
  };

  if (!currentTaskId) return null;

  return (
    <div className="relative inline-block" ref={menuRef}>
      <button
        onClick={() => !compacting && !isSending && setShowMenu(!showMenu)}
        disabled={compacting || isSending}
        className={cn(
          "relative flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors",
          compacting || isSending
            ? "cursor-not-allowed opacity-50"
            : "hover:bg-muted cursor-pointer"
        )}
        title={
          compacting
            ? `Compressing: ${compactProgress}% - ${compactPhase}`
            : `Context: ${contextTokens.toLocaleString()} / ${MAX_TOKENS.toLocaleString()} tokens${needsCompact ? " (needs compact)" : ""}`
        }
      >
        {/* SVG 环形进度条 */}
        <svg width="32" height="32" className="shrink-0">
          <circle
            cx="16"
            cy="16"
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            className="opacity-20"
          />
          <circle
            cx="16"
            cy="16"
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth="2.5"
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            transform="rotate(-90 16 16)"
            className="transition-all duration-300"
          />
          {compacting ? (
            <foreignObject x="10" y="10" width="12" height="12">
              <Loader2
                className="animate-spin"
                width="12"
                height="12"
                stroke={color}
              />
            </foreignObject>
          ) : (
            <text
              x="16"
              y="16"
              textAnchor="middle"
              dominantBaseline="central"
              className="text-[10px] font-semibold"
              fill={color}
            >
              {Math.round(percentage)}
            </text>
          )}
        </svg>

        {/* Token 数字或压缩进度 */}
        <span className="text-muted-foreground">
          {contextLoading ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : compacting ? (
            `${compactProgress}%`
          ) : (
            `${(contextTokens / 1000).toFixed(1)}K`
          )}
        </span>

        {/* 超限警告图标 */}
        {needsCompact && !compacting && (
          <AlertTriangle className="h-3 w-3 text-amber-500" />
        )}
      </button>

      {/* Dropdown 菜单 */}
      {showMenu && (
        <div className="absolute bottom-full left-0 mb-1 w-56 rounded-md border bg-popover p-1 shadow-md z-50">
          <button
            onClick={handleCompact}
            disabled={compacting || isSending || contextTokens < 10000}
            className={cn(
              "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-xs transition-colors",
              compacting || isSending || contextTokens < 10000
                ? "cursor-not-allowed opacity-50"
                : "hover:bg-accent hover:text-accent-foreground"
            )}
          >
            <Zap className="h-3.5 w-3.5" />
            <div className="text-left flex-1">
              <div className="font-medium">Compact Context</div>
              <div className="text-muted-foreground text-[10px]">
                {needsCompact
                  ? "⚠️ Context exceeds 100K"
                  : "Compress to ~40%"}
              </div>
            </div>
          </button>

          {contextTokens < 10000 && (
            <div className="px-2 py-1 text-[10px] text-muted-foreground">
              Context too small (&lt; 10K tokens)
            </div>
          )}
        </div>
      )}

      {/* 压缩进度提示（compacting时显示） */}
      {compacting && (
        <div className="absolute top-full left-0 mt-1 w-64 rounded-md border bg-blue-50 border-blue-200 p-2 shadow-lg z-50 text-xs dark:bg-blue-950 dark:border-blue-800">
          <div className="flex items-center gap-2">
            <Loader2 className="h-3 w-3 animate-spin text-blue-600 dark:text-blue-400" />
            <div className="flex-1">
              <div className="font-medium text-blue-800 dark:text-blue-300">
                Compressing... {compactProgress}%
              </div>
              <div className="text-blue-600 dark:text-blue-400 text-[10px] mt-0.5">
                {compactPhase}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 结果提示（浮动 toast） */}
      {compactResult?.show && !compacting && (
        <div
          className={cn(
            "absolute top-full left-0 mt-1 w-64 rounded-md border p-2 shadow-lg z-50 text-xs",
            compactResult.success
              ? "bg-green-50 border-green-200 text-green-800 dark:bg-green-950 dark:border-green-800 dark:text-green-300"
              : "bg-amber-50 border-amber-200 text-amber-800 dark:bg-amber-950 dark:border-amber-800 dark:text-amber-300"
          )}
        >
          {compactResult.message}
        </div>
      )}
    </div>
  );
}