"use client";

import { useState } from "react";
import { useTaskStore } from "@/stores/use-task-store";
import { confirmPlan } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { CheckCircle2, Edit3 } from "lucide-react";

export default function PlanConfirmationDialog() {
  const { currentTaskId, pendingPlan, setPendingPlan, setSubTasks } = useTaskStore();
  const [isModifying, setIsModifying] = useState(false);
  const [modifications, setModifications] = useState("");
  const [loading, setLoading] = useState(false);

  if (!pendingPlan) return null;

  const handleConfirm = async () => {
    if (!currentTaskId) return;
    
    setLoading(true);
    try {
      await confirmPlan(currentTaskId, {
        confirmed: true,
        subtasks: pendingPlan.subtasks.map((st) => ({
          task_id: currentTaskId,
          title: st.title,
          description: st.description,
          order: st.order,
        })),
      });

      // 刷新SubTask列表
      const { fetchSubTasks } = await import("@/lib/api");
      const res = await fetchSubTasks(currentTaskId);
      setSubTasks(res.data);

      setPendingPlan(null);
    } catch (err) {
      console.error("Failed to confirm plan:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleModify = async () => {
    if (!currentTaskId || !modifications.trim()) return;

    setLoading(true);
    try {
      await confirmPlan(currentTaskId, {
        confirmed: false,
        modifications: modifications.trim(),
      });

      setPendingPlan(null);
      setIsModifying(false);
      setModifications("");
    } catch (err) {
      console.error("Failed to request modifications:", err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={!!pendingPlan} onOpenChange={() => setPendingPlan(null)}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Confirm Analysis Plan</DialogTitle>
          <DialogDescription>
            {pendingPlan.message}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-4">
          {pendingPlan.subtasks.map((subtask, index) => (
            <Card key={index} className="p-3">
              <div className="flex items-start gap-3">
                <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                  {index + 1}
                </div>
                <div className="flex-1">
                  <h4 className="text-sm font-medium">{subtask.title}</h4>
                  {subtask.description && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {subtask.description}
                    </p>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>

        {isModifying && (
          <div className="space-y-2">
            <label className="text-sm font-medium">
              What would you like to change?
            </label>
            <Textarea
              value={modifications}
              onChange={(e) => setModifications(e.target.value)}
              placeholder="Describe the modifications you'd like..."
              rows={4}
            />
          </div>
        )}

        <DialogFooter>
          {!isModifying ? (
            <>
              <Button
                variant="outline"
                onClick={() => setIsModifying(true)}
                disabled={loading}
              >
                <Edit3 className="mr-2 h-4 w-4" />
                Request Changes
              </Button>
              <Button onClick={handleConfirm} disabled={loading}>
                <CheckCircle2 className="mr-2 h-4 w-4" />
                Confirm & Start
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="outline"
                onClick={() => {
                  setIsModifying(false);
                  setModifications("");
                }}
                disabled={loading}
              >
                Cancel
              </Button>
              <Button
                onClick={handleModify}
                disabled={loading || !modifications.trim()}
              >
                Submit Changes
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}