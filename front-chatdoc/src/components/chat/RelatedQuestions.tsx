import { motion } from 'framer-motion'
import { Lightbulb, MoveUpRight } from 'lucide-react'
import { cn } from '@/lib/utils'

interface RelatedQuestionsProps {
  questions: string[]
  onAsk: (question: string) => void
  disabled?: boolean   // true while another message is streaming
}

export function RelatedQuestions({ questions, onAsk, disabled }: RelatedQuestionsProps) {
  if (!questions.length) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, delay: 0.12, ease: 'easeOut' }}
      className="mt-3 pt-3 border-t border-border/40 space-y-2"
    >
      {/* Header */}
      <div className="flex items-center gap-1.5">
        <Lightbulb className="w-3 h-3 text-amber-500 shrink-0" />
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Explore Further
        </span>
      </div>

      {/* Question chips */}
      <div className="flex flex-col gap-1.5">
        {questions.map((q, i) => (
          <motion.button
            key={i}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.18, delay: 0.16 + i * 0.07, ease: 'easeOut' }}
            type="button"
            onClick={() => !disabled && onAsk(q)}
            disabled={disabled}
            className={cn(
              'group text-left text-xs px-3 py-2 rounded-lg',
              'border border-border/50 bg-muted/20',
              'flex items-start gap-2 w-full',
              disabled
                ? 'opacity-50 cursor-not-allowed'
                : [
                    'cursor-pointer',
                    'hover:border-primary/40 hover:bg-primary/5',
                    'hover:text-primary',
                    'transition-colors duration-150',
                  ],
            )}
          >
            <MoveUpRight className={cn(
              'w-3 h-3 mt-0.5 shrink-0 text-muted-foreground/70',
              !disabled && 'group-hover:text-primary transition-colors duration-150',
            )} />
            <span className="leading-snug">{q}</span>
          </motion.button>
        ))}
      </div>
    </motion.div>
  )
}
