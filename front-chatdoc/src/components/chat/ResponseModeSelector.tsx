import { Sparkles, MessageCircle, BookOpen, Code2, List, BarChart2, Briefcase, ChevronDown } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ResponseMode } from '@/types'

interface ModeConfig {
  value: ResponseMode
  label: string
  icon: typeof Sparkles
  desc: string
  color: string
}

const MODES: ModeConfig[] = [
  { value: 'auto',      label: 'Auto',      icon: Sparkles,      desc: 'Detect best format automatically', color: 'text-violet-500' },
  { value: 'simple',    label: 'Simple',    icon: MessageCircle, desc: '2–4 sentence direct answer',       color: 'text-blue-500'   },
  { value: 'detailed',  label: 'Detailed',  icon: BookOpen,      desc: 'Comprehensive with sections',      color: 'text-emerald-500' },
  { value: 'technical', label: 'Technical', icon: Code2,         desc: 'Expert depth, exact terms',        color: 'text-orange-500' },
  { value: 'summary',   label: 'Summary',   icon: List,          desc: '5–7 key bullet points',            color: 'text-cyan-500'   },
  { value: 'bullets',   label: 'Bullets',   icon: BarChart2,     desc: 'Fully structured bullet list',     color: 'text-pink-500'   },
  { value: 'executive', label: 'Executive', icon: Briefcase,     desc: 'Business-focused bottom-line',     color: 'text-amber-500'  },
]

interface Props {
  value: ResponseMode
  onChange: (mode: ResponseMode) => void
  disabled?: boolean
}

export function ResponseModeSelector({ value, onChange, disabled }: Props) {
  const current = MODES.find(m => m.value === value) ?? MODES[0]
  const Icon = current.icon

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={disabled}
          className="h-7 gap-1.5 text-xs px-2.5 border-dashed hover:border-solid"
        >
          <Icon className={cn('w-3 h-3', current.color)} />
          <span className="font-medium">{current.label}</span>
          <ChevronDown className="w-3 h-3 opacity-50" />
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="w-52">
        <DropdownMenuLabel className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium pb-1">
          Response Mode
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {MODES.map(mode => {
          const ModeIcon = mode.icon
          const isActive = mode.value === value
          return (
            <DropdownMenuItem
              key={mode.value}
              onClick={() => onChange(mode.value)}
              className={cn(
                'flex items-start gap-2.5 py-2 cursor-pointer',
                isActive && 'bg-primary/8',
              )}
            >
              <div className={cn(
                'w-6 h-6 rounded-md flex items-center justify-center shrink-0 mt-0.5',
                isActive ? 'bg-primary/15' : 'bg-muted',
              )}>
                <ModeIcon className={cn('w-3 h-3', isActive ? 'text-primary' : mode.color)} />
              </div>
              <div className="flex-1 min-w-0">
                <p className={cn('text-xs font-semibold', isActive && 'text-primary')}>
                  {mode.label}
                </p>
                <p className="text-[10px] text-muted-foreground leading-tight">{mode.desc}</p>
              </div>
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
