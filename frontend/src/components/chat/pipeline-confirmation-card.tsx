// frontend/src/components/chat/pipeline-confirmation-card.tsx

"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Database,
  ChevronDown,
  ChevronRight,
  Check,
  X,
  Code2,
  Rows3,
  Columns3,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { PipelineProposal } from "@/stores/use-task-store";

export interface ConfirmedPipelineConfig {
  table_name: string;
  display_name: string;
  description: string;
  write_strategy: string;
  transform_code: string;
  source_type: string;
  source_config: Record<string, unknown>;
  transform_description?: string;
  schema?: Array<{ name: string; type: string }>;
  row_count?: number;
}

interface PipelineConfirmationCardProps {
  pipeline: PipelineProposal;
  resolved: boolean;
  onConfirm?: (config: ConfirmedPipelineConfig) => void;
  onCancel?: () => void;
}

export default function PipelineConfirmationCard({
  pipeline,
  resolved,
  onConfirm,
  onCancel,
}: PipelineConfirmationCardProps) {
  const [tableName, setTableName] = useState(pipeline.table_name);
  const [displayName, setDisplayName] = useState(pipeline.display_name);
  const [description, setDescription] = useState(pipeline.description);
  const [writeStrategy, setWriteStrategy] = useState(pipeline.write_strategy);
  const [showCode, setShowCode] = useState(false);

  const handleConfirm = () => {
    onConfirm?.({
      table_name: tableName,
      display_name: displayName,
      description,
      write_strategy: writeStrategy,
      transform_code: pipeline.transform_code,
      source_type: pipeline.source_type,
      source_config: pipeline.source_config,
      transform_description: pipeline.transform_description,
      schema: pipeline.schema,
      row_count: pipeline.row_count,
    } as ConfirmedPipelineConfig);
  };
  
  return (
    <div className="flex gap-3 justify-start">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-500 text-white">
        <Database className="h-4 w-4" />
      </div>
      <div
        className={cn(
          "max-w-[85%] w-full rounded-lg border p-4 space-y-4",
          resolved
            ? "border-muted bg-muted/30 opacity-70"
            : "border-emerald-200 bg-emerald-50/50 dark:border-emerald-800 dark:bg-emerald-950/30"
        )}
      >
        {/* Header */}
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-emerald-600" />
          <span className="font-semibold text-sm">
            Save as Derived Data Source
          </span>
          {resolved && (
            <span className="ml-auto text-xs text-muted-foreground flex items-center gap-1">
              <Check className="h-3 w-3" /> Confirmed
            </span>
          )}
        </div>

        {/* Transform description */}
        {pipeline.transform_description && (
          <p className="text-xs text-muted-foreground leading-relaxed">
            {pipeline.transform_description}
          </p>
        )}

        {/* Editable fields */}
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">
                Table Name
              </label>
              <Input
                value={tableName}
                onChange={(e) => setTableName(e.target.value)}
                disabled={resolved}
                className="h-8 text-xs font-mono"
                placeholder="snake_case_name"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">
                Display Name
              </label>
              <Input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                disabled={resolved}
                className="h-8 text-xs"
              />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">
              Description
            </label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={resolved}
              className="h-8 text-xs"
            />
          </div>
        </div>

        {/* Schema Preview Table */}
        {pipeline.schema && pipeline.schema.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Columns3 className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-medium">Schema Preview</span>
              <span className="text-[10px] text-muted-foreground">
                ({pipeline.schema.length} columns)
              </span>
            </div>
            <div className="rounded-md border overflow-hidden max-h-40 overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/50">
                    <TableHead className="h-7 text-[10px] px-2">
                      Column
                    </TableHead>
                    <TableHead className="h-7 text-[10px] px-2">
                      Type
                    </TableHead>
                    <TableHead className="h-7 text-[10px] px-2">
                      Sample
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pipeline.schema.map((col) => {
                    const sampleVal = pipeline.sample_rows?.[0]?.[col.name];
                    return (
                      <TableRow key={col.name}>
                        <TableCell className="py-1 px-2 text-[11px] font-mono">
                          {col.name}
                        </TableCell>
                        <TableCell className="py-1 px-2 text-[11px] text-muted-foreground">
                          {col.type}
                        </TableCell>
                        <TableCell className="py-1 px-2 text-[11px] text-muted-foreground truncate max-w-[120px]">
                          {sampleVal != null ? String(sampleVal) : "—"}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        {/* Row count + Write strategy */}
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Rows3 className="h-3.5 w-3.5" />
            <span>{pipeline.row_count.toLocaleString()} rows</span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">Write:</span>
            {["replace", "append"].map((strategy) => (
              <button
                key={strategy}
                disabled={resolved}
                onClick={() => setWriteStrategy(strategy)}
                className={cn(
                  "rounded-full px-2.5 py-0.5 text-[11px] font-medium border transition-colors",
                  writeStrategy === strategy
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-background text-muted-foreground border-border hover:bg-muted"
                )}
              >
                {strategy.charAt(0).toUpperCase() + strategy.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Collapsible code */}
        <div>
          <button
            onClick={() => setShowCode(!showCode)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            {showCode ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
            <Code2 className="h-3.5 w-3.5" />
            <span>Transform Code</span>
          </button>
          {showCode && (
            <pre className="mt-2 overflow-x-auto rounded-md bg-zinc-900 p-3 text-[11px] text-green-400 leading-relaxed max-h-48 overflow-y-auto">
              <code>{pipeline.transform_code}</code>
            </pre>
          )}
        </div>

        {/* Action buttons */}
        {!resolved && (
          <div className="flex items-center justify-end gap-2 pt-1 border-t">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={onCancel}
            >
              <X className="h-3.5 w-3.5 mr-1" />
              Cancel
            </Button>
            <Button
              size="sm"
              className="h-7 text-xs bg-emerald-600 hover:bg-emerald-700"
              onClick={handleConfirm}
              disabled={!tableName.trim()}
            >
              <Database className="h-3.5 w-3.5 mr-1" />
              Confirm & Save
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}