// frontend/src/components/chat/markdown-renderer.tsx

"use client";

/**
 * Markdown + KaTeX 渲染组件
 * 支持 GFM（表格/删除线/任务列表）、数学公式（$inline$ / $$block$$）、代码高亮
 */
import React, { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import remarkGfm from "remark-gfm";
import rehypeKatex from "rehype-katex";
import { cn } from "@/lib/utils";

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

function MarkdownRendererRaw({ content, className }: MarkdownRendererProps) {
  return (
    <div className={cn("markdown-body", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          // ── 代码块（```code```）──
          pre: ({ children }) => (
            <pre className="overflow-x-auto rounded-md bg-zinc-900 p-3 text-xs leading-relaxed my-2">
              {children}
            </pre>
          ),
          // ── 行内代码 & 块级代码内层 ──
          code: ({ className: langClass, children, ...props }) => {
            // 有 language-xxx class 说明是 fenced code block 内部的 <code>
            if (langClass && /language-/.test(langClass)) {
              return (
                <code
                  className={cn("text-green-400 font-mono text-xs", langClass)}
                  {...props}
                >
                  {children}
                </code>
              );
            }
            // 行内代码
            return (
              <code
                className="rounded bg-zinc-200 dark:bg-zinc-700 px-1.5 py-0.5 text-[0.85em] font-mono"
                {...props}
              >
                {children}
              </code>
            );
          },
          // ── 表格样式 ──
          table: ({ children }) => (
            <div className="overflow-x-auto my-2">
              <table className="min-w-full border-collapse text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-muted/60">{children}</thead>
          ),
          th: ({ children }) => (
            <th className="border border-border px-2 py-1.5 text-left font-medium">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-border px-2 py-1.5">{children}</td>
          ),
          // ── 链接 ──
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline underline-offset-2 hover:text-primary/80"
            >
              {children}
            </a>
          ),
          // ── 列表 ──
          ul: ({ children }) => (
            <ul className="list-disc pl-5 my-1.5 space-y-0.5">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-5 my-1.5 space-y-0.5">{children}</ol>
          ),
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          // ── 段落 ──
          p: ({ children }) => <p className="my-1.5 leading-relaxed">{children}</p>,
          // ── 标题 ──
          h1: ({ children }) => (
            <h1 className="text-lg font-bold mt-4 mb-2">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-base font-bold mt-3 mb-1.5">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-sm font-bold mt-2.5 mb-1">{children}</h3>
          ),
          // ── 引用块 ──
          blockquote: ({ children }) => (
            <blockquote className="border-l-3 border-primary/40 pl-3 my-2 text-muted-foreground italic">
              {children}
            </blockquote>
          ),
          // ── 水平线 ──
          hr: () => <hr className="my-3 border-border" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export const MarkdownRenderer = memo(MarkdownRendererRaw);