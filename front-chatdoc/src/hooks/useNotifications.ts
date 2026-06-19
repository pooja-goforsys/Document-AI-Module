import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getNotifications,
  getUnreadCount,
  markNotificationRead,
  markAllNotificationsRead,
  deleteNotification as deleteNotificationApi,
} from '@/services/api'
import type { NotificationListResponse } from '@/types'

// ── Keys ──────────────────────────────────────────────────────────────────────

export const notificationKeys = {
  all:   ['notifications'] as const,
  count: ['notifications', 'count'] as const,
  list:  (page: number, unreadOnly: boolean) =>
    ['notifications', 'list', page, unreadOnly] as const,
}

// ── Unread count (polling) ────────────────────────────────────────────────────

export function useUnreadCount() {
  const { data } = useQuery({
    queryKey: notificationKeys.count,
    queryFn:  getUnreadCount,
    refetchInterval: 30_000,  // poll every 30 seconds
    staleTime:       15_000,
    select: (d) => d.count,
  })
  return data ?? 0
}

// ── Notification list ─────────────────────────────────────────────────────────

export function useNotificationList(page: number, unreadOnly: boolean) {
  return useQuery({
    queryKey: notificationKeys.list(page, unreadOnly),
    queryFn:  () => getNotifications(page, 20, unreadOnly),
    staleTime: 5_000,
    placeholderData: (prev) => prev,
  })
}

// ── Mutations ─────────────────────────────────────────────────────────────────

export function useMarkAsRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => markNotificationRead(id),
    onMutate: async (id) => {
      // Optimistic: mark unread count down immediately
      queryClient.setQueryData(notificationKeys.count, (old: { count: number } | undefined) =>
        old ? { count: Math.max(0, old.count - 1) } : old,
      )
      // Optimistic: flip is_read in any cached list
      queryClient.setQueriesData<NotificationListResponse>(
        { queryKey: ['notifications', 'list'] },
        (old) => {
          if (!old) return old
          return {
            ...old,
            unread: Math.max(0, old.unread - 1),
            items: old.items.map((n) => n.id === id ? { ...n, is_read: true } : n),
          }
        },
      )
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.all })
    },
  })
}

export function useMarkAllAsRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: markAllNotificationsRead,
    onMutate: () => {
      queryClient.setQueryData(notificationKeys.count, { count: 0 })
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.all })
    },
  })
}

export function useDeleteNotification() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteNotificationApi(id),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.all })
    },
  })
}
