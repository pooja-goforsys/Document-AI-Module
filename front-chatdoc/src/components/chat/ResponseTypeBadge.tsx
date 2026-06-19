import {
  Table2, BarChart3, GitBranch, Code2, Clock,
  FileText, GitCompareArrows, Sigma, BookOpen,
} from 'lucide-react'
import type { AIResponseType } from '@/types'
import { cn } from '@/lib/utils'

const CONFIG: Record<AIResponseType, { label: string; icon: React.ReactNode; className: string }> = {
  text:       { label: 'Text',       icon: <FileText     className="w-3 h-3" />, className: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300' },
  table:      { label: 'Table',      icon: <Table2       className="w-3 h-3" />, className: 'bg-blue-100  text-blue-700  dark:bg-blue-900/50 dark:text-blue-300' },
  chart:      { label: 'Chart',      icon: <BarChart3    className="w-3 h-3" />, className: 'bg-violet-100 text-violet-700 dark:bg-violet-900/50 dark:text-violet-300' },
  diagram:    { label: 'Diagram',    icon: <GitBranch    className="w-3 h-3" />, className: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300' },
  code:       { label: 'Code',       icon: <Code2        className="w-3 h-3" />, className: 'bg-amber-100  text-amber-700  dark:bg-amber-900/50 dark:text-amber-300' },
  timeline:   { label: 'Timeline',   icon: <Clock        className="w-3 h-3" />, className: 'bg-rose-100   text-rose-700   dark:bg-rose-900/50 dark:text-rose-300' },
  comparison: { label: 'Comparison', icon: <GitCompareArrows className="w-3 h-3" />, className: 'bg-cyan-100   text-cyan-700   dark:bg-cyan-900/50 dark:text-cyan-300' },
  formula:    { label: 'Formula',    icon: <Sigma        className="w-3 h-3" />, className: 'bg-pink-100   text-pink-700   dark:bg-pink-900/50 dark:text-pink-300' },
  summary:    { label: 'Summary',    icon: <BookOpen     className="w-3 h-3" />, className: 'bg-teal-100   text-teal-700   dark:bg-teal-900/50 dark:text-teal-300' },
}

interface Props {
  type: AIResponseType
  className?: string
}

export function ResponseTypeBadge({ type, className }: Props) {
  const cfg = CONFIG[type] ?? CONFIG.text
  return (
    <span className={cn(
      'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium',
      cfg.className,
      className,
    )}>
      {cfg.icon}
      {cfg.label}
    </span>
  )
}
