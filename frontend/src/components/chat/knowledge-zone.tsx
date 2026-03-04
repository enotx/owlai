// frontend/src/components/chat/knowledge-zone.tsx

"use client";

/**
 * Knowledge Zone：展示当前 Task 的知识文件标签 + 上传入口
 */
import { useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useTaskStore } from "@/stores/use-task-store";
import { uploadKnowledge } from "@/lib/api";
import { Plus, X, FileSpreadsheet, FileText } from "lucide-react";

export default function KnowledgeZone() {
  const { currentTaskId, knowledgeList, addKnowledge, removeKnowledge } = useTaskStore();
  const fileInputRef = useRef<HTMLInputElement>(null);

  /* 上传文件 */
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !currentTaskId) return;
    try {
      const res = await uploadKnowledge(currentTaskId, file);
      addKnowledge(res.data);
    } catch (err) {
      console.error("Upload failed:", err);
    }
    // 重置 input 以便重复选同一文件
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  /* 删除 Knowledge */
  const handleRemove = async (id: string) => {
    try {
      const { deleteKnowledge: delApi } = await import("@/lib/api");
      await delApi(id);
      removeKnowledge(id);
    } catch (err) {
      console.error("Delete failed:", err);
    }
  };

  if (!currentTaskId) return null;

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
            className="gap-1.5 pl-2 pr-1 py-1.5 text-xs font-normal"
          >
            {k.type === "csv" ? (
              <FileSpreadsheet className="h-3 w-3" />
            ) : (
              <FileText className="h-3 w-3" />
            )}
            {k.name}
            <button
              className="ml-0.5 rounded-full p-0.5 hover:bg-muted-foreground/20 transition-colors"
              onClick={() => handleRemove(k.id)}
            >
              <X className="h-3 w-3" />
            </button>
          </Badge>
        ))}
        {/* 上传按钮 */}
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
          accept=".csv,.txt,.md"
          className="hidden"
          onChange={handleUpload}
        />
      </div>
    </div>
  );
}