// frontend/src/components/data/data-panel.tsx

"use client";

/**
 * 右侧面板：数据表格展示
 * 点击 Knowledge Zone 中的 CSV 文件后，展示真实预览数据
 */
import { useTaskStore } from "@/stores/use-task-store";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TableProperties, DatabaseZap, MousePointerClick } from "lucide-react";
import { cn } from "@/lib/utils";

export default function DataPanel() {
  const { currentTaskId, previewData, previewColumns, previewSource } = useTaskStore();

  const hasData = previewColumns.length > 0 && previewData && previewData.length > 0;

  return (
    <div className="flex h-full flex-col border-l">
      {/* 标题栏 */}
      <div className="flex items-center gap-2 border-b px-4 py-3">
        <TableProperties className="h-5 w-5 text-primary" />
        <h2 className="text-sm font-semibold tracking-tight">Data View</h2>
        {hasData && previewSource && (
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-medium",
              previewSource.type === "step"
                ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300"
                : "bg-muted text-muted-foreground"
            )}
          >
            {previewSource.type === "step"
              ? `⚡ ${previewSource.dfName}`
              : `📁 ${previewSource.name}`}
          </span>
        )}
        {hasData && (
          <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
            {previewData!.length} rows
          </span>
        )}
      </div>

      {/* 内容区域 */}
      {!currentTaskId ? (
        /* 未选择 Task */
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted-foreground">
          <DatabaseZap className="h-10 w-10 opacity-30" />
          <p className="text-sm">Select a task to view data</p>
        </div>
      ) : !hasData ? (
        /* 已选 Task 但未预览数据 */
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted-foreground">
          <MousePointerClick className="h-10 w-10 opacity-30" />
          <p className="text-sm">Click a file in Knowledge or Execution Section to preview</p>
        </div>
      ) : (
        /* 展示真实预览表格 */
        <ScrollArea className="flex-1">
          <div className="min-w-max">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50 hover:bg-muted/50">
                  {previewColumns.map((col) => (
                    <TableHead
                      key={col}
                      className="h-9 whitespace-nowrap px-3 text-xs font-semibold"
                    >
                      {col}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {previewData!.map((row, idx) => (
                  <TableRow key={idx} className="hover:bg-muted/30">
                    {previewColumns.map((col) => (
                      <TableCell
                        key={col}
                        className="whitespace-nowrap px-3 py-2 text-xs tabular-nums"
                      >
                        {row[col] != null ? String(row[col]) : ""}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <ScrollBar orientation="horizontal" />
        </ScrollArea>
      )}
    </div>
  );
}