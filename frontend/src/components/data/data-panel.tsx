// frontend/src/components/data/data-panel.tsx

"use client";

/**
 * 右侧面板：数据表格展示
 * 当前使用 Mock 数据演示，后续接入真实 Knowledge 预览
 */
import { useTaskStore } from "@/stores/use-task-store";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TableProperties, DatabaseZap } from "lucide-react";

/** 演示用 Mock 数据 */
const MOCK_COLUMNS = [
  "二级类目",
  "词数",
  "总UV",
  "绝对缺口UV",
  "相对缺口UV(5km)",
  "相对缺口UV(3km)",
  "缺口中可代偿占比",
];

const MOCK_ROWS: Record<string, string | number>[] = [
  { 二级类目: "内分泌系统", 词数: 567, 总UV: "1,240,223", 绝对缺口UV: "383,444", "相对缺口UV(5km)": "181,952", "相对缺口UV(3km)": "217,959", 缺口中可代偿占比: "20.79%" },
  { 二级类目: "胃肠用药", 词数: "2,213", 总UV: "3,918,080", 绝对缺口UV: "223,046", "相对缺口UV(5km)": "44,200", "相对缺口UV(3km)": "55,030", 缺口中可代偿占比: "35.17%" },
  { 二级类目: "妇科用药", 词数: "1,286", 总UV: "1,890,052", 绝对缺口UV: "100,852", "相对缺口UV(5km)": "22,392", "相对缺口UV(3km)": "28,068", 缺口中可代偿占比: "31.20%" },
  { 二级类目: "心脑血管", 词数: "1,339", 总UV: "1,982,749", 绝对缺口UV: "212,403", "相对缺口UV(5km)": "22,257", "相对缺口UV(3km)": "31,154", 缺口中可代偿占比: "26.68%" },
  { 二级类目: "滋补调养", 词数: 980, 总UV: "1,058,201", 绝对缺口UV: "109,541", "相对缺口UV(5km)": "21,990", "相对缺口UV(3km)": "28,949", 缺口中可代偿占比: "24.71%" },
  { 二级类目: "皮肤用药", 词数: "2,504", 总UV: "3,707,327", 绝对缺口UV: "171,468", "相对缺口UV(5km)": "19,487", "相对缺口UV(3km)": "25,822", 缺口中可代偿占比: "43.12%" },
  { 二级类目: "风湿骨伤", 词数: "1,465", 总UV: "1,547,888", 绝对缺口UV: "94,013", "相对缺口UV(5km)": "19,002", "相对缺口UV(3km)": "23,176", 缺口中可代偿占比: "37.66%" },
  { 二级类目: "五官用药", 词数: "2,749", 总UV: "4,062,099", 绝对缺口UV: "120,567", "相对缺口UV(5km)": "17,377", "相对缺口UV(3km)": "22,393", 缺口中可代偿占比: "44.03%" },
  { 二级类目: "神经系统", 词数: 538, 总UV: "579,775", 绝对缺口UV: "67,349", "相对缺口UV(5km)": "16,608", "相对缺口UV(3km)": "21,342", 缺口中可代偿占比: "23.79%" },
  { 二级类目: "呼吸系统", 词数: "1,787", 总UV: "2,517,609", 绝对缺口UV: "103,361", "相对缺口UV(5km)": "15,978", "相对缺口UV(3km)": "20,759", 缺口中可代偿占比: "39.53%" },
  { 二级类目: "抗菌消炎", 词数: 995, 总UV: "2,368,484", 绝对缺口UV: "74,825", "相对缺口UV(5km)": "8,271", "相对缺口UV(3km)": "11,037", 缺口中可代偿占比: "37.69%" },
];

export default function DataPanel() {
  const { currentTaskId, previewData, previewColumns } = useTaskStore();

  // 决定展示来源：真实数据 > Mock 数据
  const columns = previewColumns.length > 0 ? previewColumns : MOCK_COLUMNS;
  const rows = previewData && previewData.length > 0 ? previewData : MOCK_ROWS;

  return (
    <div className="flex h-full flex-col border-l">
      {/* 标题栏 */}
      <div className="flex items-center gap-2 border-b px-4 py-3">
        <TableProperties className="h-5 w-5 text-primary" />
        <h2 className="text-sm font-semibold tracking-tight">Data View</h2>
        {currentTaskId && (
          <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
            {rows.length} rows
          </span>
        )}
      </div>

      {/* 数据表格 */}
      {!currentTaskId ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted-foreground">
          <DatabaseZap className="h-10 w-10 opacity-30" />
          <p className="text-sm">Select a task to view data</p>
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div className="min-w-max">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/50 hover:bg-muted/50">
                  {columns.map((col) => (
                    <TableHead
                      key={col}
                      className="h-9 whitespace-nowrap px-3 text-xs font-semibold"
                    >
                      {col}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row, idx) => (
                  <TableRow key={idx} className="hover:bg-muted/30">
                    {columns.map((col) => (
                      <TableCell
                        key={col}
                        className="whitespace-nowrap px-3 py-2 text-xs tabular-nums"
                      >
                        {String(row[col] ?? "")}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <ScrollBar orientation="horizontal" />
        </ScrollArea>
      )}
    </div>
  );
}