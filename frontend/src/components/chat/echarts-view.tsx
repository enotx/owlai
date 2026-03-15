// frontend/src/components/chat/echarts-view.tsx

"use client";

import React, { useEffect, useRef } from "react";

type EChartsOption = Record<string, unknown>;

export default function EChartsView({
  option,
  height = 360,
}: {
  option: EChartsOption;
  height?: number;
}) {
  const divRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<unknown>(null);

  useEffect(() => {
    let disposed = false;

    async function mount() {
      if (!divRef.current) return;

      const echarts = await import("echarts");
      if (disposed) return;

      // 初始化
      const chart = echarts.init(divRef.current);
      chart.setOption(option as any, { notMerge: true });

      chartRef.current = chart;

      const onResize = () => {
        try {
          (chart as any).resize();
        } catch {
          // ignore
        }
      };
      window.addEventListener("resize", onResize);

      return () => {
        window.removeEventListener("resize", onResize);
        try {
          (chart as any).dispose();
        } catch {
          // ignore
        }
      };
    }

    const cleanupPromise = mount();

    return () => {
      disposed = true;
      // eslint-disable-next-line @typescript-eslint/no-floating-promises
      Promise.resolve(cleanupPromise).then((cleanup) => cleanup && cleanup());
    };
  }, [option]);

  return (
    <div
      ref={divRef}
      className="w-full rounded-md border bg-background"
      style={{ height }}
    />
  );
}