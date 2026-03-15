// frontend/src/components/data/data-panel.tsx

"use client";

import { useState, useEffect } from "react";
import { useTaskStore } from "@/stores/use-task-store";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { Download } from "lucide-react";
import { downloadKnowledge, exportStepDataframe, fetchVisualizations, type VisualizationItem } from "@/lib/api";
import EChartsView from "@/components/chat/echarts-view";


import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { TableProperties, DatabaseZap, MousePointerClick, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import { previewKnowledge } from "@/lib/api";

export default function DataPanel() {
  const { currentTaskId, previewData, previewColumns, previewSource, setPreviewData } = useTaskStore();
  const [selectedSheet, setSelectedSheet] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"data" | "charts">("data");
  const [vizList, setVizList] = useState<VisualizationItem[]>([]);
  const [selectedViz, setSelectedViz] = useState<VisualizationItem | null>(null);

  const hasData = previewColumns.length > 0 && previewData && previewData.length > 0;
  const isTextPreview = previewSource?.fileType === "text" && previewSource?.textContent;

  // 拉取可视化列表
  useEffect(() => {
    if (!currentTaskId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchVisualizations(currentTaskId);
        if (cancelled) return;
        setVizList(res.data);
        // 默认选中最新一个
        if (res.data.length > 0) {
          setSelectedViz(res.data[res.data.length - 1]);
        } else {
          setSelectedViz(null);
        }
      } catch (e) {
        console.error("Failed to fetch visualizations:", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentTaskId]);

  // 切换Excel sheet
  const handleSheetChange = async (sheetName: string) => {
    if (!previewSource?.knowledgeId) return;
    
    try {
      const res = await previewKnowledge(previewSource.knowledgeId, 50, sheetName);
      const data = res.data;
      setPreviewData(data.rows, data.columns, {
        ...previewSource,
        currentSheet: sheetName,
      });
      setSelectedSheet(sheetName);
    } catch (err) {
      console.error("Sheet switch failed:", err);
    }
  };

  // 在组件内部添加导出处理函数
  const handleExport = async () => {
    if (!previewSource) return;
    
    try {
      if (previewSource.type === "knowledge" && previewSource.knowledgeId) {
        // Knowledge导出：直接下载源文件
        await downloadKnowledge(previewSource.knowledgeId);
      } else if (previewSource.type === "step" && previewSource.stepId && previewSource.dfName) {
        // DataFrame导出：转Excel下载
        await exportStepDataframe(previewSource.stepId, previewSource.dfName);
      }
    } catch (err) {
      console.error("Export failed:", err);
    }
  };

  return (
    <div className="flex h-full flex-col border-l">
    {/* 标题栏 */}
    <div className="flex items-center gap-2 border-b px-4 py-3">
      <TableProperties className="h-5 w-5 text-primary" />
      <h2 className="text-sm font-semibold tracking-tight">Data View</h2>

      <div className="ml-2 flex items-center gap-1 rounded-md border bg-muted/30 p-0.5">
        <Button
          variant={activeTab === "data" ? "default" : "ghost"}
          size="sm"
          className="h-6 px-2 text-[11px]"
          onClick={() => setActiveTab("data")}
        >
          Data
        </Button>
        <Button
          variant={activeTab === "charts" ? "default" : "ghost"}
          size="sm"
          className="h-6 px-2 text-[11px]"
          onClick={() => setActiveTab("charts")}
        >
          Charts
        </Button>
      </div>

      {/* 数据源标签 */}
      {(hasData || isTextPreview) && previewSource && (
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
      
      {/* Export按钮 - 仅在有数据且不是文本预览时显示 */}
      {hasData && !isTextPreview && (
        <Button
          variant="outline"
          size="sm"
          className="ml-auto h-7 gap-1.5 text-xs"
          onClick={handleExport}
        >
          <Download className="h-3.5 w-3.5" />
          Export
        </Button>
      )}
      
      {/* 行数统计 */}
      {hasData && (
        <span className={cn(
          "rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground",
          !isTextPreview && "ml-0"  // 如果有Export按钮，不需要ml-auto
        )}>
          {previewData.length} rows
        </span>
      )}
    </div>

      {/* Excel Sheet 切换器 */}
      {previewSource?.fileType === "excel" && previewSource?.availableSheets && (
        <div className="flex items-center gap-2 border-b px-4 py-2 bg-muted/30">
          <span className="text-xs text-muted-foreground">Sheet:</span>
          <div className="flex gap-1">
            {previewSource.availableSheets.map((sheet) => (
              <Button
                key={sheet}
                variant={sheet === (selectedSheet || previewSource.currentSheet) ? "default" : "outline"}
                size="sm"
                className="h-6 text-xs"
                onClick={() => handleSheetChange(sheet)}
              >
                {sheet}
              </Button>
            ))}
          </div>
        </div>
      )}

      {/* 内容区域 */}
      {!currentTaskId ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted-foreground">
          <DatabaseZap className="h-10 w-10 opacity-30" />
          <p className="text-sm">Select a task to view data</p>
        </div>
      ) : activeTab === "charts" ? (
        <div className="flex flex-1 flex-col">
          <div className="border-b px-3 py-2 text-xs text-muted-foreground">
            {vizList.length} charts
          </div>
          <div className="flex flex-1 min-h-0">
            {/* 左侧：图表列表 */}
            <div className="w-[220px] shrink-0 border-r">
              <ScrollArea className="h-full">
                <div className="p-2 space-y-1">
                  {vizList.length === 0 ? (
                    <div className="p-3 text-xs text-muted-foreground">
                      No charts yet. Ask Owl to visualize results.
                    </div>
                  ) : (
                    vizList
                      .slice()
                      .reverse()
                      .map((v) => (
                        <button
                          key={v.id}
                          className={cn(
                            "w-full rounded-md border px-2 py-2 text-left text-xs hover:bg-muted/40",
                            selectedViz?.id === v.id
                              ? "border-primary bg-muted"
                              : "border-transparent"
                          )}
                          onClick={() => setSelectedViz(v)}
                        >
                          <div className="font-medium line-clamp-2">{v.title}</div>
                          <div className="mt-1 text-[10px] text-muted-foreground">
                            {v.chart_type}
                          </div>
                        </button>
                      ))
                  )}
                </div>
              </ScrollArea>
            </div>
            {/* 右侧：预览 */}
            <div className="flex-1 min-w-0">
              <ScrollArea className="h-full">
                <div className="p-3">
                  {!selectedViz ? (
                    <div className="text-xs text-muted-foreground">
                      Select a chart to preview.
                    </div>
                  ) : (
                    (() => {
                      let option: Record<string, unknown> | null = null;
                      try {
                        option = JSON.parse(selectedViz.option_json);
                      } catch {
                        option = null;
                      }
                      return (
                        <div className="space-y-2">
                          <div className="text-sm font-semibold">
                            {selectedViz.title}
                          </div>
                          {option ? (
                            <EChartsView option={option} height={420} />
                          ) : (
                            <div className="text-xs text-red-600">
                              Invalid chart option_json.
                            </div>
                          )}
                        </div>
                      );
                    })()
                  )}
                </div>
              </ScrollArea>
            </div>
          </div>
        </div>
      ) : isTextPreview ? (
        /* 文本预览模式 */
        <ScrollArea className="flex-1">
          <div className="p-4">
            <div className="rounded-lg border bg-muted/30 p-4">
              <div className="flex items-center gap-2 mb-3 pb-2 border-b">
                <FileText className="h-4 w-4 text-muted-foreground" />
                <span className="text-xs font-medium text-muted-foreground">Text Content</span>
              </div>
              <pre className="text-xs leading-relaxed whitespace-pre-wrap break-words font-mono">
                {previewSource.textContent}
              </pre>
            </div>
          </div>
        </ScrollArea>
      ) : !hasData ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted-foreground">
          <MousePointerClick className="h-10 w-10 opacity-30" />
          <p className="text-sm">Click a file in Knowledge or Execution Section to preview</p>
        </div>
      ) : (
        /* 表格预览模式 */
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
                {previewData.map((row, idx) => (
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