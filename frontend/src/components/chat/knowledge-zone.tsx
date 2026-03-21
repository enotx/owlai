// frontend/src/components/chat/knowledge-zone.tsx

"use client";

import { useRef, useState, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useTaskStore } from "@/stores/use-task-store";
import { uploadKnowledge } from "@/lib/api";
import { Plus, X, FileSpreadsheet, FileText, Sheet } from "lucide-react";


export default function KnowledgeZone() {
  const { currentTaskId, knowledgeList, addKnowledge, removeKnowledge, setPreviewData } = useTaskStore();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounterRef = useRef(0);

  // 通用文件上传处理
  const processFile = useCallback(async (file: File) => {
    if (!currentTaskId) return;
    const allowedExts = [".csv", ".txt", ".md", ".xlsx", ".xls"];
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!allowedExts.includes(ext)) {
      console.warn(`Unsupported file type: ${ext}`);
      return;
    }

    // 前端快速查重：检查当前 knowledgeList 中是否已有同名文件
    const duplicate = knowledgeList.find(
      (k) => k.name.toLowerCase() === file.name.toLowerCase()
    );
    if (duplicate) {
      alert(`File "${file.name}" already exists in this task. Please rename or delete the existing one first.`);
      return;
    }

    try {
      const res = await uploadKnowledge(currentTaskId, file);
      addKnowledge(res.data);
    } catch (err: unknown) {
      // 后端 409 兜底处理
      if (err && typeof err === "object" && "response" in err) {
        const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } };
        if (axiosErr.response?.status === 409) {
          alert(axiosErr.response.data?.detail || `File "${file.name}" already exists.`);
          return;
        }
      }
      console.error("Upload failed:", err);
    }
  }, [currentTaskId, addKnowledge, knowledgeList]);
  
  // 点击上传
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await processFile(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // 拖拽事件：进入区域
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    if (e.dataTransfer.types.includes("Files")) {
      setIsDragging(true);
    }
  }, []);

  // 拖拽事件：悬停（必须 preventDefault 才能触发 drop）
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  // 拖拽事件：离开区域（用计数器防子元素闪烁）
  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) {
      setIsDragging(false);
    }
  }, []);

  // 拖拽事件：释放文件，支持多文件依次上传
  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    dragCounterRef.current = 0;

    const files = Array.from(e.dataTransfer.files);
    for (const file of files) {
      await processFile(file);
    }
  }, [processFile]);

  // 删除知识库项
  const handleRemove = async (id: string) => {
    try {
      const { deleteKnowledge: delApi } = await import("@/lib/api");
      await delApi(id);
      removeKnowledge(id);
    } catch (err) {
      console.error("Delete failed:", err);
    }
  };

  const handlePreview = async (k: (typeof knowledgeList)[0]) => {
    try {
      const { previewKnowledge } = await import("@/lib/api");
      const res = await previewKnowledge(k.id);
      const data = res.data;
      
      if (data.type === "text") {
        // 文本文件预览
        setPreviewData([], [], {
          type: "knowledge",
          name: k.name,
          fileType: "text",
          textContent: data.content,
        });
      } else {
        // 表格文件预览（CSV/Excel）
        setPreviewData(data.rows, data.columns, {
          type: "knowledge",
          name: k.name,
          fileType: data.type,
          availableSheets: data.available_sheets,
          currentSheet: data.current_sheet,
          knowledgeId: k.id,
        });
      }
    } catch (err) {
      console.error("Preview failed:", err);
    }
  };

  if (!currentTaskId) return null;

  // 根据文件类型返回图标
  const getFileIcon = (type: string) => {
    if (type === "csv") return <FileSpreadsheet className="h-3 w-3" />;
    if (type === "excel") return <Sheet className="h-3 w-3" />;
    return <FileText className="h-3 w-3" />;
  };

  return (
    <div
      className={`rounded-lg border bg-card p-3 transition-colors ${
        isDragging ? "border-primary border-dashed bg-primary/5" : ""
      }`}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <h3 className="mb-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wider">
        Knowledge Zone
      </h3>

      {/* 拖拽中提示 */}
      {isDragging && (
        <div className="mb-2 flex items-center justify-center rounded border border-dashed border-primary/50 bg-primary/5 py-2 text-xs text-primary">
          Drop files here to upload (.csv, .xlsx, .xls, .txt, .md)
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {knowledgeList.map((k) => (
          <Badge
            key={k.id}
            variant="secondary"
            className="gap-1.5 pl-2 pr-1 py-1.5 text-xs font-normal cursor-pointer hover:bg-secondary/80 transition-colors"
            onClick={() => handlePreview(k)}
          >
            {getFileIcon(k.type)}
            {k.name}
            <button
              className="ml-0.5 rounded-full p-0.5 hover:bg-muted-foreground/20 transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                handleRemove(k.id);
              }}
            >
              <X className="h-3 w-3" />
            </button>
          </Badge>
        ))}

        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1 text-xs"
          onClick={() => fileInputRef.current?.click()}
        >
          <Plus className="h-3 w-3" />
          More
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,.txt,.md,.xlsx,.xls"
          className="hidden"
          onChange={handleUpload}
        />
      </div>
    </div>
  );
}