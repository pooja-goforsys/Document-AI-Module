import { motion, AnimatePresence } from 'framer-motion'
import { Brain, Search, Pen } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { StatusStep } from '@/types'

interface Step {
  key: StatusStep
  icon: typeof Brain
  defaultLabel: string
}

const STEPS: Step[] = [
  { key: 'thinking',   icon: Brain,  defaultLabel: 'Analyzing question…' },
  { key: 'searching',  icon: Search, defaultLabel: 'Searching documents…' },
  { key: 'generating', icon: Pen,    defaultLabel: 'Generating answer…'   },
]

interface Props {
  step: StatusStep
  label?: string
}

export function StatusIndicator({ step, label }: Props) {
  const currentIdx = STEPS.findIndex(s => s.key === step)

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.2 }}
        className="flex flex-col gap-2 py-1"
      >
        {STEPS.map((s, idx) => {
          const done   = idx < currentIdx
          const active = idx === currentIdx
          const Icon   = s.icon

          return (
            <motion.div
              key={s.key}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: active || done ? 1 : 0.3, x: 0 }}
              transition={{ delay: idx * 0.06, duration: 0.2 }}
              className={cn(
                'flex items-center gap-2.5 text-xs',
                done   && 'text-muted-foreground/50',
                active && 'text-foreground',
                !done && !active && 'text-muted-foreground/30',
              )}
            >
              <div className={cn(
                'w-5 h-5 rounded-full flex items-center justify-center shrink-0',
                done   && 'bg-primary/15',
                active && 'bg-primary/20',
                !done && !active && 'bg-muted/40',
              )}>
                {active ? (
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1.4, repeat: Infinity, ease: 'linear' }}
                  >
                    <Icon className="w-2.5 h-2.5 text-primary" />
                  </motion.div>
                ) : (
                  <Icon className={cn('w-2.5 h-2.5', done ? 'text-primary/50' : 'text-muted-foreground/30')} />
                )}
              </div>

              <span className={cn('font-medium', active && 'text-primary/80')}>
                {active && label ? label : s.defaultLabel}
              </span>

              {active && (
                <span className="flex gap-0.5 ml-0.5">
                  {[0, 1, 2].map(i => (
                    <motion.span
                      key={i}
                      className="w-1 h-1 rounded-full bg-primary/60"
                      animate={{ opacity: [0.3, 1, 0.3] }}
                      transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.2 }}
                    />
                  ))}
                </span>
              )}
            </motion.div>
          )
        })}
      </motion.div>
    </AnimatePresence>
  )
}
