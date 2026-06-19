import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Bell, CheckCheck, Filter, ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { NotificationItem } from '@/components/notifications/NotificationItem'
import {
  useNotificationList,
  useMarkAsRead,
  useMarkAllAsRead,
  useDeleteNotification,
} from '@/hooks/useNotifications'

const PAGE_SIZE = 20

export default function NotificationsPage() {
  const [page, setPage]           = useState(1)
  const [unreadOnly, setUnreadOnly] = useState(false)

  const { data, isLoading, isFetching } = useNotificationList(page, unreadOnly)
  const markRead    = useMarkAsRead()
  const markAll     = useMarkAllAsRead()
  const deleteNotif = useDeleteNotification()

  const notifications = data?.items    ?? []
  const total         = data?.total    ?? 0
  const unread        = data?.unread   ?? 0
  const totalPages    = Math.max(1, Math.ceil(total / PAGE_SIZE))

  function handleFilterChange(newUnreadOnly: boolean) {
    setUnreadOnly(newUnreadOnly)
    setPage(1)
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      {/* Page header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Notifications</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {unread > 0
              ? `${unread} unread notification${unread !== 1 ? 's' : ''}`
              : 'All caught up'}
          </p>
        </div>

        {unread > 0 && (
          <Button
            variant="outline"
            size="sm"
            className="gap-2 shrink-0"
            onClick={() => markAll.mutate()}
            disabled={markAll.isPending}
          >
            <CheckCheck className="w-4 h-4" />
            Mark all as read
          </Button>
        )}
      </div>

      {/* Filter tabs */}
      <div className="flex items-center gap-1 p-1 bg-muted rounded-lg w-fit mb-5">
        {[
          { label: 'All',    value: false },
          { label: 'Unread', value: true  },
        ].map(({ label, value }) => (
          <button
            key={label}
            onClick={() => handleFilterChange(value)}
            className={cn(
              'px-4 py-1.5 rounded-md text-sm font-medium transition-all',
              unreadOnly === value
                ? 'bg-background shadow-sm text-foreground'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* List */}
      <div className={cn(
        'bg-card border rounded-xl overflow-hidden',
        isFetching && 'opacity-70 transition-opacity',
      )}>
        {isLoading ? (
          <div className="divide-y">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex gap-3 px-4 py-3">
                <Skeleton className="w-8 h-8 rounded-full shrink-0 mt-0.5" />
                <div className="flex-1 space-y-1.5 py-0.5">
                  <Skeleton className="h-4 w-2/3" />
                  <Skeleton className="h-3 w-full" />
                  <Skeleton className="h-2.5 w-1/4" />
                </div>
              </div>
            ))}
          </div>
        ) : notifications.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-4 py-16 px-6 text-center">
            <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center">
              <Bell className="w-7 h-7 text-muted-foreground/40" />
            </div>
            <div>
              <p className="text-base font-semibold text-foreground/70">
                {unreadOnly ? 'No unread notifications' : 'No notifications yet'}
              </p>
              <p className="text-sm text-muted-foreground mt-1 max-w-xs">
                {unreadOnly
                  ? 'Switch to "All" to see your notification history.'
                  : 'Notifications will appear here when documents are uploaded, indexed, or processed.'}
              </p>
            </div>
            {unreadOnly && (
              <Button variant="outline" size="sm" onClick={() => handleFilterChange(false)}>
                <Filter className="w-3.5 h-3.5 mr-1.5" />
                Show all
              </Button>
            )}
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {notifications.map((n, i) => (
              <motion.div
                key={n.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0, height: 0 }}
                className={cn(i !== notifications.length - 1 && 'border-b')}
              >
                <NotificationItem
                  notification={n}
                  onMarkAsRead={(id) => markRead.mutate(id)}
                  onDelete={(id) => deleteNotif.mutate(id)}
                />
              </motion.div>
            ))}
          </AnimatePresence>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-sm text-muted-foreground">
            Page {page} of {totalPages} · {total} total
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
            >
              <ChevronLeft className="w-4 h-4" />
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
            >
              Next
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
