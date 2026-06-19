import { useMemo, useId, useState } from 'react'
import type { RecentQuery } from '@/types'
import { cn } from '@/lib/utils'

const DAYS = 7

interface DayPoint {
  label: string
  shortDate: string
  count: number
  x: number
  y: number
}

function buildPoints(queries: RecentQuery[], W: number, H: number, padX: number, padY: number): DayPoint[] {
  const counts: Record<string, number> = {}
  queries.forEach(q => {
    const key = new Date(q.created_at).toISOString().slice(0, 10)
    counts[key] = (counts[key] ?? 0) + 1
  })

  const raw = Array.from({ length: DAYS }, (_, i) => {
    const d = new Date()
    d.setDate(d.getDate() - (DAYS - 1 - i))
    const key = d.toISOString().slice(0, 10)
    const label = d.toLocaleDateString('en-US', { weekday: 'short' })
    return { label, shortDate: key, count: counts[key] ?? 0 }
  })

  const maxCount = Math.max(...raw.map(r => r.count), 1)
  const plotW = W - padX * 2
  const plotH = H - padY * 2

  return raw.map((r, i) => ({
    ...r,
    x: padX + (i / (DAYS - 1)) * plotW,
    y: padY + (1 - r.count / maxCount) * plotH,
  }))
}

function smoothPath(pts: DayPoint[]): string {
  if (pts.length < 2) return ''
  let d = `M ${pts[0].x},${pts[0].y}`
  for (let i = 1; i < pts.length; i++) {
    const p = pts[i - 1], c = pts[i]
    const cpx = (p.x + c.x) / 2
    d += ` C ${cpx},${p.y} ${cpx},${c.y} ${c.x},${c.y}`
  }
  return d
}

interface QueryActivityChartProps {
  queries: RecentQuery[]
  todayCount: number
}

export function QueryActivityChart({ queries, todayCount }: QueryActivityChartProps) {
  const uid = useId().replace(/:/g, '')
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)

  const W = 300, H = 64, PAD_X = 6, PAD_Y = 8
  const points = useMemo(() => buildPoints(queries, W, H, PAD_X, PAD_Y), [queries])
  const totalWeek = useMemo(() => points.reduce((s, p) => s + p.count, 0), [points])

  const linePath = smoothPath(points)
  const fillPath = `${linePath} L ${points[points.length - 1].x},${H} L ${points[0].x},${H} Z`

  const colW = (W - PAD_X * 2) / (DAYS - 1)

  return (
    <div>
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Query Activity</p>
          <p className="text-3xl font-bold mt-0.5">{totalWeek.toLocaleString()}</p>
          <p className="text-xs text-muted-foreground">queries last 7 days</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground">Today</p>
          <p className="text-2xl font-semibold">{todayCount}</p>
        </div>
      </div>

      {/* Chart */}
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          style={{ height: '64px' }}
          onMouseLeave={() => setHoveredIdx(null)}
          aria-label="Query activity over 7 days"
        >
          <defs>
            <linearGradient id={`fill-${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"   stopColor="hsl(var(--primary))" stopOpacity="0.25" />
              <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0.02" />
            </linearGradient>
          </defs>

          {/* Area fill */}
          <path d={fillPath} fill={`url(#fill-${uid})`} />

          {/* Line */}
          <path
            d={linePath}
            fill="none"
            stroke="hsl(var(--primary))"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Invisible hover targets */}
          {points.map((p, i) => (
            <rect
              key={i}
              x={p.x - colW / 2}
              y={0}
              width={colW}
              height={H}
              fill="transparent"
              onMouseEnter={() => setHoveredIdx(i)}
            />
          ))}

          {/* Dots */}
          {points.map((p, i) => (
            <circle
              key={i}
              cx={p.x}
              cy={p.y}
              r={hoveredIdx === i ? 4.5 : 3}
              fill={hoveredIdx === i ? 'hsl(var(--primary))' : 'hsl(var(--background))'}
              stroke="hsl(var(--primary))"
              strokeWidth="2"
              style={{ transition: 'r 0.12s ease, fill 0.12s ease' }}
            />
          ))}
        </svg>

        {/* Tooltip */}
        {hoveredIdx !== null && (() => {
          const p = points[hoveredIdx]
          const leftPct = (p.x / W) * 100
          return (
            <div
              className="absolute -top-9 bg-popover border rounded-lg px-2.5 py-1 shadow-md text-xs pointer-events-none z-10 whitespace-nowrap"
              style={{ left: `${leftPct}%`, transform: 'translateX(-50%)' }}
            >
              <span className="font-semibold">{p.count}</span>
              <span className="text-muted-foreground ml-1">{p.label}</span>
            </div>
          )
        })()}
      </div>

      {/* Day labels */}
      <div className="flex justify-between mt-1.5 px-1">
        {points.map((p, i) => (
          <span
            key={i}
            className={cn(
              'text-[10px] transition-colors duration-100',
              hoveredIdx === i ? 'text-primary font-semibold' : 'text-muted-foreground',
            )}
          >
            {p.label}
          </span>
        ))}
      </div>
    </div>
  )
}
