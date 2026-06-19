import { FileText, Sparkles, AlertCircle, Bell, Trash2 } from 'lucide-react'
import { motion } from 'framer-motion'
import { cn, formatRelativeTime } from '@/lib/utils'
import type { Notification, NotificationType } from '@/types'

// ── Type → visual config ──────────────────────────────────────────────────────

const TYPE_CONFIG: Record<
  NotificationType,
  { Icon: typeof Bell; iconColor: string; bg: string; dot: string }
> = {
  document: {
    Icon: FileText,
    iconColor: 'text-blue-500',
    bg:        'bg-blue-500/10 dark:bg-blue-500/15',
    dot:       'bg-blue-500',
  },
  ai: {
    Icon: Sparkles,
    iconColor: 'text-violet-500',
    bg:        'bg-violet-500/10 dark:bg-violet-500/15',
    dot:       'bg-violet-500',
  },
  error: {
    Icon: AlertCircle,
    iconColor: 'text-red-500',
    bg:        'bg-red-500/10 dark:bg-red-500/15',
    dot:       'bg-red-500',
  },
  system: {
    Icon: Bell,
    iconColor: 'text-muted-foreground',
    bg:        'bg-muted/60',
    dot:       'bg-muted-foreground',
  },
}

interface NotificationItemProps {
  notification: Notification
  onMarkAsRead: (id: string) => void
  onDelete: (id: string) => void
  compact?: boolean
}

export function NotificationItem({
  notification,
  onMarkAsRead,
  onDelete,
  compact = false,
}: NotificationItemProps) {
  const cfg = TYPE_CONFIG[notification.type as NotificationType] ?? TYPE_CONFIG.system
  const { Icon } = cfg

  function handleClick() {
    if (!notification.is_read) {
      onMarkAsRead(notification.id)
    }
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: -8 }}
      transition={{ duration: 0.18 }}
      onClick={handleClick}
      className={cn(
        'group relative flex items-start gap-3 px-4 py-3 transition-colors cursor-pointer',
        'hover:bg-muted/50',
        !notification.is_read && 'bg-primary/[0.03]',
        compact && 'px-3 py-2.5',
      )}
    >
      {/* Type icon */}
      <div className={cn(
        'w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-0.5',
        cfg.bg,
      )}>
        <Icon className={cn('w-3.5 h-3.5', cfg.iconColor)} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pr-6">
        <p className={cn(
          'text-sm leading-snug',
          !notification.is_read ? 'font-semibold text-foreground' : 'font-medium text-foreground/80',
        )}>
          {notification.title}
        </p>
        <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed line-clamp-2">
          {notification.message}
        </p>
        <p className="text-[10px] text-muted-foreground/60 mt-1 font-medium">
          {formatRelativeTime(notification.created_at)}
        </p>
      </div>

      {/* Unread dot */}
      {!notification.is_read && (
        <span className={cn('absolute right-10 top-4 w-1.5 h-1.5 rounded-full shrink-0', cfg.dot)} />
      )}

      {/* Delete button (shown on hover) */}
      <button
        onClick={(e) => { e.stopPropagation(); onDelete(notification.id) }}
        className={cn(
          'absolute right-3 top-3 p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity',
          'hover:bg-destructive/10 hover:text-destructive',
          'text-muted-foreground/50',
        )}
        title="Delete notification"
      >
        <Trash2 className="w-3 h-3" />
      </button>
    </motion.div>
  )
}
