import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

export interface TrendSeries {
  name: string
  data: Array<{ date: string; value: string }>
  color?: string
}

export default function TrendChart({
  series,
  height = 220,
}: {
  series: TrendSeries[]
  height?: number
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const chart = echarts.init(el)
    const dates = Array.from(
      new Set(series.flatMap((s) => s.data.map((p) => p.date))),
    ).sort()
    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: {
        top: 0,
        textStyle: { color: '#94a3b8', fontSize: 11 },
        type: 'scroll',
      },
      grid: { left: 56, right: 16, top: 32, bottom: 24 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { color: '#64748b', fontSize: 10 },
        axisLine: { lineStyle: { color: '#334155' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#64748b', fontSize: 10 },
        splitLine: { lineStyle: { color: '#1e293b' } },
      },
      series: series
        .filter((s) => s.data.length > 0)
        .map((s) => ({
          name: s.name,
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: s.data.map((p) => Number(p.value)),
          lineStyle: { width: 2, color: s.color },
          itemStyle: { color: s.color },
        })),
    })
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(el)
    return () => {
      observer.disconnect()
      chart.dispose()
    }
  }, [series])

  return <div ref={ref} style={{ height }} />
}
