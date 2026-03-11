// frontend/src/components/chat/knowledge-zone.tsx

"use client";

import { useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useTaskStore } from "@/stores/use-task-store";
import { uploadKnowledge } from "@/lib/api";
import { Plus, X, FileSpreadsheet, FileText, Sheet } from "lucide-react";

export default function KnowledgeZone() {
  const { currentTaskId, knowledgeList, addKnowledge, removeKnowledge, setPreviewData } = useTaskStore();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !currentTaskId) return;
    try {
      const res = await uploadKnowledge(currentTaskId, file);
      addKnowledge(res.data);
    } catch (err) {
      console.error("Upload failed:", err);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

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
    <div className="rounded-lg border bg-card p-3">
      <h3 className="mb-2 text-center text-xs font-medium text-muted-foreground uppercase tracking-wider">
        Knowledge Zone
      </h3>
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