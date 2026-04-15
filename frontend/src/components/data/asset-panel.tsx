// frontend/src/components/data/asset-panel.tsx

"use client";

import { useEffect, useState, useCallback } from "react";
import {
  fetchAssets,
  fetchDataPipelines,
  deleteAsset,
  updateAsset,
  type AssetData,
  type DataPipelineData,
} from "@/lib/api";

import { useTaskStore } from "@/stores/use-task-store";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Play,
  Trash2,
  Code2,
  FileText,
  Database,
  ChevronDown,
  ChevronUp,
  Pencil,
  Check,
  X,
  Eye,
  Copy,
} from "lucide-react";
import { cn } from "@/lib/utils";

type TabId = "scripts" | "pipelines" | "sops";

export default function AssetPanel() {
  const [assets, setAssets] = useState<AssetData[]>([]);
  const [pipelines, setPipelines] = useState<DataPipelineData[]>([]);
  const [activeTab, setActiveTab] = useState<TabId>("scripts");
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const loadAssets = useCallback(async () => {
    setLoading(true);
    try {
      if (activeTab === "pipelines") {
        const res = await fetchDataPipelines();
        setPipelines(res.data);
        setAssets([]);
        return;
      }

      let params: {
        asset_type?: "script" | "sop";
        script_type?: "general" | "pipeline";
      } = {};

      if (activeTab === "scripts") {
        params = { asset_type: "script", script_type: "general" };
      } else {
        params = { asset_type: "sop" };
      }

      const res = await fetchAssets(params);
      setAssets(res.data);
      setPipelines([]);
    } catch (err) {
      console.error("Failed to load assets:", err);
      setAssets([]);
      setPipelines([]);
    } finally {
      setLoading(false);
    }
  }, [activeTab]);

  useEffect(() => {
    loadAssets();
  }, [loadAssets]);

  const handleDelete = async (assetId: string) => {
    if (!confirm("Delete this asset?")) return;
    try {
      await deleteAsset(assetId);
      setAssets((prev) => prev.filter((a) => a.id !== assetId));
      if (expandedId === assetId) setExpandedId(null);
    } catch (err) {
      console.error("Failed to delete asset:", err);
    }
  };

  const handleStartEdit = (asset: AssetData) => {
    setEditingId(asset.id);
    setEditName(asset.name);
    setEditDesc(asset.description || "");
  };

  const handleSaveEdit = async (assetId: string) => {
    try {
      const res = await updateAsset(assetId, {
        name: editName.trim() || undefined,
        description: editDesc.trim() || undefined,
      });
      setAssets((prev) =>
        prev.map((a) => (a.id === assetId ? res.data : a))
      );
      setEditingId(null);
    } catch (err) {
      console.error("Failed to update asset:", err);
    }
  };

  const handleCopyCode = async (code: string, assetId: string) => {
    try {
      await navigator.clipboard.writeText(code);
      setCopiedId(assetId);
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      // fallback
    }
  };

  const handleRun = (asset: AssetData) => {
    // Store the asset to run and switch to the run dialog
    // For now, dispatch a custom event that page.tsx can listen to
    const event = new CustomEvent("owl:run-asset", { detail: asset });
    window.dispatchEvent(event);
  };

  const getIcon = () => {
    switch (activeTab) {
      case "scripts":
        return <Code2 className="h-4 w-4" />;
      case "pipelines":
        return <Database className="h-4 w-4" />;
      case "sops":
        return <FileText className="h-4 w-4" />;
    }
  };

  return (
    <div className="flex h-full flex-col">
      {/* Tabs */}
      <div className="flex border-b">
        {(
          [
            { id: "scripts" as const, label: "Scripts" },
            { id: "pipelines" as const, label: "Pipelines" },
            { id: "sops" as const, label: "SOPs" },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "px-4 py-2 text-sm font-medium transition-colors",
              activeTab === tab.id
                ? "border-b-2 border-primary text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Asset List */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {loading ? (
          <div className="text-center text-sm text-muted-foreground py-8">
            Loading...
          </div>
        ) : assets.length === 0 ? (
          <div className="text-center text-sm text-muted-foreground py-8">
            <div className="mb-2">{getIcon()}</div>
            No {activeTab} yet.
            <br />
            <span className="text-xs">
              Use{" "}
              <code className="rounded bg-muted px-1 py-0.5">
                /{activeTab === "sops" ? "sop" : activeTab === "pipelines" ? "derive" : "script"}
              </code>{" "}
              in a task to extract one.
            </span>
          </div>
        ) : activeTab === "pipelines" ? (
          pipelines.map((pipeline) => {
            const isExpanded = expandedId === pipeline.id;

            return (
              <Card key={pipeline.id} className="overflow-hidden">
                <div className="p-4">
                  <div className="flex items-start gap-3">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <Database className="h-4 w-4" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-sm truncate">
                        {pipeline.name}
                      </h3>
                      {pipeline.description && (
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                          {pipeline.description}
                        </p>
                      )}

                      <div className="flex flex-wrap gap-1.5 mt-2">
                        <span className="text-[10px] rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
                          target: {pipeline.target_table_name}
                        </span>
                        <span className="text-[10px] rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
                          {pipeline.write_strategy}
                        </span>
                        <span className="text-[10px] rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
                          {pipeline.status}
                        </span>
                      </div>

                      <div className="flex items-center gap-1.5 mt-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            setExpandedId(isExpanded ? null : pipeline.id)
                          }
                          className="h-7 text-xs"
                        >
                          <Eye className="h-3 w-3 mr-1" />
                          {isExpanded ? "Hide" : "View"}
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>

                {isExpanded && (
                  <div className="border-t bg-muted/20">
                    <div className="p-4">
                      <div className="text-xs font-medium text-muted-foreground mb-2">
                        Transform Code
                      </div>
                      <pre className="text-xs overflow-x-auto max-h-80 leading-relaxed">
                        <code>{pipeline.transform_code}</code>
                      </pre>
                    </div>
                  </div>
                )}
              </Card>
            );
          })
        ) : (
          assets.map((asset) => {
            const isExpanded = expandedId === asset.id;
            const isEditing = editingId === asset.id;
            return (
              <Card key={asset.id} className="overflow-hidden">
                <div className="p-4">
                  {/* Header row */}
                  <div className="flex items-start gap-3">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      {getIcon()}
                    </div>
                    <div className="flex-1 min-w-0">
                      {isEditing ? (
                        <div className="space-y-2">
                          <input
                            value={editName}
                            onChange={(e) => setEditName(e.target.value)}
                            className="w-full rounded border px-2 py-1 text-sm font-medium bg-background"
                            autoFocus
                          />
                          <input
                            value={editDesc}
                            onChange={(e) => setEditDesc(e.target.value)}
                            placeholder="Description..."
                            className="w-full rounded border px-2 py-1 text-xs bg-background"
                          />
                          <div className="flex gap-1">
                            <Button
                              size="sm"
                              className="h-6 text-xs"
                              onClick={() => handleSaveEdit(asset.id)}
                            >
                              <Check className="h-3 w-3 mr-1" />
                              Save
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-6 text-xs"
                              onClick={() => setEditingId(null)}
                            >
                              <X className="h-3 w-3" />
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <h3 className="font-medium text-sm truncate">
                            {asset.name}
                          </h3>
                          {asset.description && (
                            <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                              {asset.description}
                            </p>
                          )}
                        </>
                      )}

                      {/* Meta badges */}
                      {!isEditing && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {asset.code && (
                            <span className="text-[10px] rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
                              {asset.code.split("\n").length} lines
                            </span>
                          )}
                          {asset.allowed_modules.length > 0 && (
                            <span className="text-[10px] rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
                              {asset.allowed_modules.length} modules
                            </span>
                          )}
                          {Object.keys(asset.env_vars).length > 0 && (
                            <span className="text-[10px] rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
                              {Object.keys(asset.env_vars).length} env vars
                            </span>
                          )}
                        </div>
                      )}

                      {/* Actions */}
                      {!isEditing && (
                        <div className="flex items-center gap-1.5 mt-2">
                          {asset.asset_type === "script" && (
                            <Button
                              size="sm"
                              onClick={() => handleRun(asset)}
                              className="h-7 text-xs"
                            >
                              <Play className="h-3 w-3 mr-1" />
                              Run
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              setExpandedId(isExpanded ? null : asset.id)
                            }
                            className="h-7 text-xs"
                          >
                            <Eye className="h-3 w-3 mr-1" />
                            {isExpanded ? "Hide" : "View"}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleStartEdit(asset)}
                            className="h-7 text-xs"
                          >
                            <Pencil className="h-3 w-3" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleDelete(asset.id)}
                            className="h-7 text-xs text-destructive hover:text-destructive"
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Expanded code/content view */}
                {isExpanded && (
                  <div className="border-t bg-muted/20">
                    {asset.code && (
                      <div className="relative">
                        <div className="flex items-center justify-between px-4 py-1.5 border-b bg-muted/30">
                          <span className="text-xs font-medium text-muted-foreground">
                            Code
                          </span>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 text-xs"
                            onClick={() =>
                              handleCopyCode(asset.code!, asset.id)
                            }
                          >
                            <Copy className="h-3 w-3 mr-1" />
                            {copiedId === asset.id ? "Copied!" : "Copy"}
                          </Button>
                        </div>
                        <pre className="p-4 text-xs overflow-x-auto max-h-80 leading-relaxed">
                          <code>{asset.code}</code>
                        </pre>
                      </div>
                    )}
                    {asset.content_markdown && (
                      <div className="p-4">
                        <div className="text-xs font-medium text-muted-foreground mb-2">
                          Content
                        </div>
                        <pre className="text-xs whitespace-pre-wrap max-h-80 overflow-y-auto">
                          {asset.content_markdown}
                        </pre>
                      </div>
                    )}
                    {Object.keys(asset.env_vars).length > 0 && (
                      <div className="px-4 py-3 border-t">
                        <div className="text-xs font-medium text-muted-foreground mb-1.5">
                          Environment Variables
                        </div>
                        <div className="space-y-1">
                          {Object.entries(asset.env_vars).map(([key, val]) => (
                            <div key={key} className="text-xs font-mono">
                              <span className="text-primary">{key}</span>
                              <span className="text-muted-foreground">
                                {" "}
                                = {val.length > 30
                                  ? val.slice(0, 30) + "..."
                                  : val}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </Card>
            );
          })
        )}
      </div>
    </div>
  );
}