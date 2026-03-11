"use client";

import { useEffect } from "react";
import { useTaskStore } from "@/stores/use-task-store";
import { fetchSubTasks } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, Circle, Loader2, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const STATUS_CONFIG = {
  pending: {
    icon: Circle,
    label: "Pending",
    color: "text-muted-foreground",
    bgColor: "bg-muted",
  },
  running: {
    icon: Loader2,
    label: "Running",
    color: "text-blue-600",
    bgColor: "bg-blue-50 dark:bg-blue-950",
    animate: "animate-spin",
  },
  completed: {
    icon: CheckCircle2,
    label: "Completed",
    color: "text-green-600",
    bgColor: "bg-green-50 dark:bg-green-950",
  },
  failed: {
    icon: XCircle,
    label: "Failed",
    color: "text-red-600",
    bgColor: "bg-red-50 dark:bg-red-950",
  },
};

export default function SubTaskList() {
  const { currentTaskId, subtasks, setSubTasks } = useTaskStore();

  useEffect(() => {
    if (!currentTaskId) return;
    
    fetchSubTasks(currentTaskId)
      .then((res) => setSubTasks(res.data))
      .catch((err) => console.error("Failed to fetch subtasks:", err));
  }, [currentTaskId, setSubTasks]);

  if (!currentTaskId || subtasks.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-muted-foreground">Task Plan</h3>
      <div className="space-y-2">
        {subtasks.map((subtask, index) => {
          const config = STATUS_CONFIG[subtask.status];
          const Icon = config.icon;

          return (
            <Card
              key={subtask.id}
              className={cn(
                "p-3 transition-colors",
                config.bgColor
              )}
            >
              <div className="flex items-start gap-3">
                <div className="flex h-6 w-6 shrink-0 items-center justify-center">
                  <Icon
                    className={cn("h-4 w-4", config.color)}
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-muted-foreground">
                      Step {index + 1}
                    </span>
                    <Badge variant="outline" className="text-xs">
                      {config.label}
                    </Badge>
                  </div>
                  <h4 className="mt-1 text-sm font-medium">{subtask.title}</h4>
                  {subtask.description && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {subtask.description}
                    </p>
                  )}
                  {subtask.result && subtask.status === "completed" && (
                    <p className="mt-2 text-xs text-green-700 dark:text-green-400">
                      ✓ {subtask.result}
                    </p>
                  )}
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}