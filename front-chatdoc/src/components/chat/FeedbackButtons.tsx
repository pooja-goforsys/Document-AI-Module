import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ThumbsUp, ThumbsDown, Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { FeedbackRating } from '@/types'

interface Props {
  messageId: string
  currentFeedback?: FeedbackRating | null
  onFeedback: (messageId: string, rating: FeedbackRating) => Promise<void>
}

export function FeedbackButtons({ messageId, currentFeedback, onFeedback }: Props) {
  const [pending, setPending] = useState<FeedbackRating | null>(null)
  const [justSubmitted, setJustSubmitted] = useState<FeedbackRating | null>(null)

  async function handleClick(rating: FeedbackRating) {
    if (pending) return
    setPending(rating)
    try {
      await onFeedback(messageId, rating)
      setJustSubmitted(rating)
      setTimeout(() => setJustSubmitted(null), 1500)
    } finally {
      setPending(null)
    }
  }

  const active = currentFeedback ?? justSubmitted

  return (
    <div className="flex items-center gap-0.5">
      <AnimatePresence mode="wait">
        {justSubmitted ? (
          <motion.div
            key="thanks"
            initial={{ opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
            className="flex items-center gap-1 text-[10px] text-muted-foreground px-1"
          >
            <Check className="w-3 h-3 text-green-500" />
            <span>Thanks!</span>
          </motion.div>
        ) : (
          <motion.div key="buttons" className="flex items-center gap-0.5">
            {(['like', 'dislike'] as FeedbackRating[]).map(rating => (
              <motion.button
                key={rating}
                onClick={() => handleClick(rating)}
                disabled={!!pending}
                whileHover={{ scale: 1.1 }}
                whileTap={{ scale: 0.9 }}
                className={cn(
                  'p-1 rounded transition-colors',
                  'hover:bg-muted/80',
                  active === rating && rating === 'like'    && 'text-green-500 bg-green-500/10',
                  active === rating && rating === 'dislike' && 'text-red-500 bg-red-500/10',
                  active !== rating && 'text-muted-foreground/50 hover:text-muted-foreground',
                )}
                title={rating === 'like' ? 'Helpful' : 'Not helpful'}
              >
                {rating === 'like'
                  ? <ThumbsUp   className="w-3.5 h-3.5" />
                  : <ThumbsDown className="w-3.5 h-3.5" />
                }
              </motion.button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
