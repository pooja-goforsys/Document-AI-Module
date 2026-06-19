import { useState, useEffect, useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Bell } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useUnreadCount } from '@/hooks/useNotifications'
import { NotificationDropdown } from './NotificationDropdown'

export function NotificationBell() {
  const [open, setOpen]           = useState(false)
  const containerRef              = useRef<HTMLDivElement>(null)
  const unreadCount               = useUnreadCount()
  const prevUnreadRef             = useRef(unreadCount)
  const [pulse, setPulse]         = useState(false)

  // Pulse animation when new notifications arrive
  useEffect(() => {
    if (unreadCount > prevUnreadRef.current) {
      setPulse(true)
      const t = setTimeout(() => setPulse(false), 700)
      return () => clearTimeout(t)
    }
    prevUnreadRef.current = unreadCount
  }, [unreadCount])

  // Close on click outside
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Close on Escape
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    if (open) document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open])

  return (
    <div className="relative" ref={containerRef}>
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setOpen((o) => !o)}
        aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ''}`}
        aria-expanded={open}
        className={cn('relative', open && 'bg-accent')}
      >
        <motion.div
          animate={pulse ? { scale: [1, 1.3, 1] } : {}}
          transition={{ duration: 0.35 }}
        >
          <Bell className="w-4 h-4" />
        </motion.div>

        {/* Badge */}
        <AnimatePresence>
          {unreadCount > 0 && (
            <motion.span
              key="badge"
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0 }}
              transition={{ type: 'spring', stiffness: 500, damping: 30 }}
              className={cn(
                'absolute top-0.5 right-0.5 min-w-[16px] h-4 px-1',
                'rounded-full bg-destructive text-destructive-foreground',
                'text-[9px] font-bold flex items-center justify-center',
                'pointer-events-none leading-none',
              )}
            >
              {unreadCount > 99 ? '99+' : unreadCount}
            </motion.span>
          )}
        </AnimatePresence>
      </Button>

      {/* Dropdown */}
      <AnimatePresence>
        {open && <NotificationDropdown onClose={() => setOpen(false)} />}
      </AnimatePresence>
    </div>
  )
}
