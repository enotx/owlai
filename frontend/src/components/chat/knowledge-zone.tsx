// frontend/src/components/chat/knowledge-zone.tsx

"use client";

import { useRef, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { useTaskStore } from "@/stores/use-task-store";
import { uploadKnowledge } from "@/lib/api";
import { X, FileSpreadsheet, FileText, Sheet, Database, Settings, Layers } from "lucide-react";

export default function KnowledgeZone() {
  const { currentTaskId, knowledgeList, addKnowledge, removeKnowledge, setPreviewData } = useTaskStore();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounterRef = useRef(0);

  const processFile = useCallback(async (file: File) => {
    if (!currentTaskId) return;
    const allowedExts = [".csv", ".txt", ".md", ".xlsx", ".xls"];
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!allowedExts.includes(ext)) {
      console.warn(`Unsupported file type: ${ext}`);
      return;
    }

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

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await processFile(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    if (e.dataTransfer.types.includes("Files")) setIsDragging(true);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) setIsDragging(false);
  }, []);

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
        setPreviewData([], [], {
          type: "knowledge", name: k.name, fileType: "text", textContent: data.content,
        });
      } else {
        setPreviewData(data.rows, data.columns, {
          type: "knowledge", name: k.name, fileType: data.type,
          availableSheets: data.available_sheets, currentSheet: data.current_sheet, knowledgeId: k.id,
        });
      }
    } catch (err) {
      console.error("Preview failed:", err);
    }
  };

  if (!currentTaskId) return null;

  const getFileIcon = (type: string) => {
    if (type === "csv") return <FileSpreadsheet className="h-5 w-5 text-green-600" />;
    if (type === "excel") return <Sheet className="h-5 w-5 text-blue-600" />;
    return <FileText className="h-5 w-5 text-gray-500" />;
  };

  const getFileMeta = (k: (typeof knowledgeList)[0]) => {
    const ext = k.name.slice(k.name.lastIndexOf(".")).toLowerCase();
    if (ext === ".csv") return "CSV Data";
    if (ext === ".xlsx" || ext === ".xls") return "Excel Sheet";
    if (ext === ".md") return "Markdown";
    return "Text File";
  };

  return (
    <div
      className={`rounded-xl border-2 border-dashed p-4 transition-colors ${
        isDragging ? "border-primary bg-primary/5" : ""
      }`}
      style={{
        borderColor: isDragging ? undefined : "var(--owl-dropzone-border)",
        background: isDragging ? undefined : "var(--owl-dropzone-bg)",
      }}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* File cards */}
      <div className="flex flex-wrap items-start gap-3 mb-3">
        {knowledgeList.map((k) => (
          <div
            key={k.id}
            className="group relative flex items-center gap-2.5 rounded-lg border bg-card px-3 py-2.5 cursor-pointer hover:shadow-sm transition-shadow"
            onClick={() => handlePreview(k)}
          >
            {getFileIcon(k.type)}
            <div className="min-w-0">
              <div className="text-sm font-medium truncate max-w-[140px]">{k.name}</div>
              <div className="text-[10px] text-muted-foreground">{getFileMeta(k)}</div>
            </div>
            <button
              className="ml-1 rounded-full p-0.5 opacity-0 group-hover:opacity-100 hover:bg-muted-foreground/20 transition-all"
              onClick={(e) => {
                e.stopPropagation();
                handleRemove(k.id);
              }}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>

      {/* Drop zone prompt */}
      <div
        className="flex items-center justify-center gap-4 text-muted-foreground cursor-pointer"
        onClick={() => fileInputRef.current?.click()}
      >
        <Database className="h-4 w-4 opacity-40" />
        <Settings className="h-4 w-4 opacity-40" />
        <Layers className="h-4 w-4 opacity-40" />
        <span className="text-xs">Drop more resources here</span>
        <Layers className="h-4 w-4 opacity-40" />
        <Settings className="h-4 w-4 opacity-40" />
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".csv,.txt,.md,.xlsx,.xls"
        className="hidden"
        onChange={handleUpload}
      />
    </div>
  );
}