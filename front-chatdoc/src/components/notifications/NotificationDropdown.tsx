import { Link } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Bell, CheckCheck, ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { NotificationItem } from './NotificationItem'
import {
  useNotificationList,
  useMarkAsRead,
  useMarkAllAsRead,
  useDeleteNotification,
} from '@/hooks/useNotifications'

interface Props {
  onClose: () => void
}

export function NotificationDropdown({ onClose }: Props) {
  const { data, isLoading } = useNotificationList(1, false)
  const markRead    = useMarkAsRead()
  const markAll     = useMarkAllAsRead()
  const deleteNotif = useDeleteNotification()

  const notifications = data?.items ?? []
  const unread = data?.unread ?? 0

  return (
    <motion.div
      initial={{ opacity: 0, y: -8, scale: 0.97 }}
      animate={{ opacity: 1, y: 0,  scale: 1    }}
      exit={{    opacity: 0, y: -8, scale: 0.97 }}
      transition={{ duration: 0.15, ease: 'easeOut' }}
      className="absolute right-0 top-full mt-2 w-[380px] max-h-[520px] flex flex-col
                 bg-card border border-border rounded-xl shadow-xl z-50 overflow-hidden
                 transition-none"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b shrink-0">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold">Notifications</h3>
          {unread > 0 && (
            <span className="inline-flex items-center justify-center h-5 min-w-[20px] px-1.5
                             rounded-full bg-primary text-primary-foreground text-[10px] font-bold">
              {unread > 99 ? '99+' : unread}
            </span>
          )}
        </div>
        {unread > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs gap-1.5 text-muted-foreground hover:text-foreground"
            onClick={() => markAll.mutate()}
            disabled={markAll.isPending}
          >
            <CheckCheck className="w-3.5 h-3.5" />
            Mark all read
          </Button>
        )}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="p-4 space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex gap-3">
                <Skeleton className="w-8 h-8 rounded-full shrink-0" />
                <div className="flex-1 space-y-1.5">
                  <Skeleton className="h-3.5 w-3/4" />
                  <Skeleton className="h-3 w-full"  />
                  <Skeleton className="h-2.5 w-1/4" />
                </div>
              </div>
            ))}
          </div>
        ) : notifications.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-12 px-6 text-center">
            <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center">
              <Bell className="w-5 h-5 text-muted-foreground/50" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground/70">All caught up!</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                No notifications yet. They'll appear here.
              </p>
            </div>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {notifications.map((n) => (
              <NotificationItem
                key={n.id}
                notification={n}
                onMarkAsRead={(id) => markRead.mutate(id)}
                onDelete={(id) => deleteNotif.mutate(id)}
                compact
              />
            ))}
          </AnimatePresence>
        )}
      </div>

      {/* Footer */}
      {notifications.length > 0 && (
        <div className="px-4 py-2.5 border-t shrink-0">
          <Link
            to="/notifications"
            onClick={onClose}
            className="flex items-center justify-center gap-1.5 text-xs text-primary
                       hover:underline font-medium py-1"
          >
            View all notifications
            <ArrowRight className="w-3 h-3" />
          </Link>
        </div>
      )}
    </motion.div>
  )
}
