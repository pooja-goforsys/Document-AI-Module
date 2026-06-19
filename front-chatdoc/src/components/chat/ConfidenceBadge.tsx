import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

type Level = 'high' | 'good' | 'moderate' | 'low'

interface Props {
  score: number
  level: string
}

const CFG: Record<Level, { label: string; bar: string; text: string; bg: string; border: string }> = {
  high:     { label: 'High Confidence',     bar: 'bg-emerald-500', text: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-500/8',  border: 'border-emerald-500/20' },
  good:     { label: 'Good Match',          bar: 'bg-blue-500',    text: 'text-blue-600 dark:text-blue-400',       bg: 'bg-blue-500/8',     border: 'border-blue-500/20'    },
  moderate: { label: 'Moderate Confidence', bar: 'bg-amber-500',   text: 'text-amber-600 dark:text-amber-400',     bg: 'bg-amber-500/8',    border: 'border-amber-500/20'   },
  low:      { label: 'Low Confidence',      bar: 'bg-red-500',     text: 'text-red-600 dark:text-red-400',         bg: 'bg-red-500/8',      border: 'border-red-500/20'     },
}

export function ConfidenceBadge({ score, level }: Props) {
  const cfg = CFG[(level as Level)] ?? CFG.low
  const pct = Math.max(0, Math.min(100, score))

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className={cn(
        'flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg mt-2',
        'border',
        cfg.bg,
        cfg.border,
      )}
    >
      <span className={cn('text-[10px] font-semibold shrink-0 uppercase tracking-wide', cfg.text)}>
        {cfg.label}
      </span>

      <div className="flex-1 h-1 bg-black/10 dark:bg-white/10 rounded-full overflow-hidden min-w-[48px]">
        <motion.div
          className={cn('h-full rounded-full', cfg.bar)}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1], delay: 0.05 }}
        />
      </div>

      <span className={cn('text-[10px] font-mono font-semibold shrink-0 tabular-nums', cfg.text)}>
        {pct.toFixed(0)}%
      </span>
    </motion.div>
  )
}
