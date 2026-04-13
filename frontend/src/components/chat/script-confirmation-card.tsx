"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useTaskStore } from "@/stores/use-task-store";
import { cn } from "@/lib/utils";
import { Code2, Save, X, ChevronDown, ChevronUp } from "lucide-react";

interface ScriptProposal {
  name: string;
  description: string;
  code: string;
  script_type: string;
  env_vars: Record<string, string>;
  allowed_modules: string[];
}

interface Props {
  data: {
    title: string;
    description: string;
    script: ScriptProposal;
    options: Array<{ label: string; value: string; badge?: string }>;
  };
  onRespond: (message: string) => void;
  disabled?: boolean;
}

export default function ScriptConfirmationCard({ data, onRespond, disabled }: Props) {
  const [codeExpanded, setCodeExpanded] = useState(false);
  const [responded, setResponded] = useState(false);

  const script = data.script;
  const codeLines = (script.code || "").split("\n");
  const codePreview = codeLines.slice(0, 10).join("\n");
  const hasMore = codeLines.length > 10;

  const handleConfirm = () => {
    setResponded(true);
    const payload = JSON.stringify({
      name: script.name,
      description: script.description,
      code: script.code,
      script_type: script.script_type,
      env_vars: script.env_vars,
      allowed_modules: script.allowed_modules,
    });
    onRespond(`[Script Confirm] ${payload}`);
  };

  const handleCancel = () => {
    setResponded(true);
    onRespond(`[Script Confirm] {"cancelled": true}`);
  };

  return (
    <Card className="my-3 overflow-hidden border-primary/20 bg-primary/5">
      <div className="p-4">
        {/* Header */}
        <div className="flex items-center gap-2 mb-3">
          <Code2 className="h-5 w-5 text-primary" />
          <h3 className="font-semibold text-sm">{data.title}</h3>
        </div>

        {/* Script info */}
        <div className="space-y-2 mb-4">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Name:</span>
            <span className="text-sm font-medium">{script.name}</span>
          </div>
          {script.description && (
            <p className="text-xs text-muted-foreground">{script.description}</p>
          )}
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="rounded bg-muted px-2 py-0.5">
              Type: {script.script_type}
            </span>
            <span className="rounded bg-muted px-2 py-0.5">
              {codeLines.length} lines
            </span>
            {script.allowed_modules.length > 0 && (
              <span className="rounded bg-muted px-2 py-0.5">
                Modules: {script.allowed_modules.join(", ")}
              </span>
            )}
            {Object.keys(script.env_vars).length > 0 && (
              <span className="rounded bg-muted px-2 py-0.5">
                Env: {Object.keys(script.env_vars).join(", ")}
              </span>
            )}
          </div>
        </div>

        {/* Code preview */}
        <div className="rounded-lg border bg-background overflow-hidden">
          <div
            className="flex items-center justify-between px-3 py-1.5 border-b bg-muted/30 cursor-pointer"
            onClick={() => setCodeExpanded(!codeExpanded)}
          >
            <span className="text-xs font-medium text-muted-foreground">Code Preview</span>
            {hasMore && (
              <button className="text-xs text-muted-foreground flex items-center gap-1">
                {codeExpanded ? (
                  <><ChevronUp className="h-3 w-3" /> Collapse</>
                ) : (
                  <><ChevronDown className="h-3 w-3" /> Show all ({codeLines.length} lines)</>
                )}
              </button>
            )}
          </div>
          <pre className="p-3 text-xs overflow-x-auto max-h-80">
            <code>{codeExpanded ? script.code : codePreview}{!codeExpanded && hasMore ? "\n..." : ""}</code>
          </pre>
        </div>

        {/* Actions */}
        {!responded && (
          <div className="flex items-center gap-2 mt-4">
            <Button
              size="sm"
              onClick={handleConfirm}
              disabled={disabled}
              className="gap-1.5"
            >
              <Save className="h-3.5 w-3.5" />
              Save Script
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={handleCancel}
              disabled={disabled}
            >
              <X className="h-3.5 w-3.5 mr-1" />
              Cancel
            </Button>
          </div>
        )}

        {responded && (
          <div className="mt-3 text-xs text-muted-foreground italic">
            Response submitted.
          </div>
        )}
      </div>
    </Card>
  );
}