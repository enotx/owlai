// frontend/src/components/database/database-warning-dialog.tsx

"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { recreateDatabase } from "@/lib/api";
import { useDatabase } from "@/contexts/database-context";

interface DatabaseWarningDialogProps {
  open: boolean;
  onClose: () => void;
}

export default function DatabaseWarningDialog({ open, onClose }: DatabaseWarningDialogProps) {
  const { compatibility, recheckCompatibility } = useDatabase();
  const [isRecreating, setIsRecreating] = useState(false);
  const [recreateError, setRecreateError] = useState<string | null>(null);

  const handleRecreate = async () => {
    setIsRecreating(true);
    setRecreateError(null);

    try {
      const result = await recreateDatabase();
      
      if (result.success) {
        // 重建成功，重新检查兼容性
        await recheckCompatibility();
        onClose();
      } else {
        setRecreateError(result.message);
      }
    } catch (error) {
      setRecreateError(error instanceof Error ? error.message : "未知错误");
    } finally {
      setIsRecreating(false);
    }
  };

  if (!compatibility) return null;

  return (
    <Dialog open={open} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-yellow-500" />
            Database Compatibility Issue Detected
          </DialogTitle>
          <DialogDescription asChild>
            <div className="space-y-3 pt-2">
              <div>
                Database Compatibility Issue Detected. Please recreate the database to ensure proper functionality.
              </div>
              
              {compatibility.issues.length > 0 && (
                <div className="rounded-md bg-muted p-3">
                  <div className="mb-2 text-sm font-medium">Specific Issues:</div>
                  <ul className="list-inside list-disc space-y-1 text-sm">
                    {compatibility.issues.map((issue, index) => (
                      <li key={index} className="text-muted-foreground">
                        {issue}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="rounded-md border border-yellow-200 bg-yellow-50 p-3 dark:border-yellow-900 dark:bg-yellow-950">
                <div className="text-sm font-medium text-yellow-800 dark:text-yellow-200">
                  ⚠️ Warning: Recreating the database will delete all historical data, and this operation cannot be undone.
                </div>
              </div>

              <div className="rounded-md bg-muted p-3">
                <div className="text-xs text-muted-foreground">
                  Database Path:<br />
                  <code className="text-xs">{compatibility.db_path}</code>
                </div>
              </div>

              {recreateError && (
                <div className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-900 dark:bg-red-950">
                  <div className="text-sm text-red-800 dark:text-red-200">
                    Recreate Failed: {recreateError}
                  </div>
                </div>
              )}
            </div>
          </DialogDescription>
        </DialogHeader>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            variant="outline"
            onClick={onClose}
            disabled={isRecreating}
          >
            Skip
          </Button>
          <Button
            variant="destructive"
            onClick={handleRecreate}
            disabled={isRecreating}
          >
            {isRecreating ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Recreating...
              </>
            ) : (
              <>
                <RefreshCw className="mr-2 h-4 w-4" />
                Recreate Database
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}