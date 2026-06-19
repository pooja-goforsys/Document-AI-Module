import { Skeleton } from '@/components/ui/skeleton'

function SidebarSkeleton() {
  return (
    <div className="w-56 shrink-0 border-r bg-background flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 h-12 border-b">
        <Skeleton className="h-4 w-10" />
        <Skeleton className="h-7 w-7 rounded" />
      </div>
      <div className="p-2 space-y-1">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex items-center gap-2 px-3 py-2">
            <Skeleton className="w-3.5 h-3.5 rounded shrink-0" />
            <div className="flex-1 space-y-1">
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-2.5 w-2/3" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function MessagesSkeleton() {
  return (
    <div className="flex-1 px-6 py-4 space-y-5 overflow-hidden">
      {/* User message */}
      <div className="flex gap-3 flex-row-reverse">
        <Skeleton className="w-7 h-7 rounded-full shrink-0 mt-0.5" />
        <div className="flex flex-col items-end gap-1.5">
          <Skeleton className="h-11 w-56 rounded-2xl rounded-tr-sm" />
          <Skeleton className="h-3 w-10" />
        </div>
      </div>

      {/* AI message */}
      <div className="flex gap-3">
        <Skeleton className="w-7 h-7 rounded-full shrink-0 mt-0.5" />
        <div className="flex flex-col gap-1.5 w-full max-w-[75%]">
          <div className="rounded-2xl rounded-tl-sm border bg-card p-4 space-y-2">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-5/6" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-4/6" />
            <Skeleton className="h-3 w-5/6" />
          </div>
          <div className="flex gap-1.5">
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-5 w-24 rounded-full" />
            ))}
          </div>
          <Skeleton className="h-3 w-10" />
        </div>
      </div>

      {/* Second user message */}
      <div className="flex gap-3 flex-row-reverse">
        <Skeleton className="w-7 h-7 rounded-full shrink-0 mt-0.5" />
        <div className="flex flex-col items-end gap-1.5">
          <Skeleton className="h-11 w-72 rounded-2xl rounded-tr-sm" />
          <Skeleton className="h-3 w-10" />
        </div>
      </div>

      {/* AI typing indicator */}
      <div className="flex gap-3">
        <Skeleton className="w-7 h-7 rounded-full shrink-0 mt-0.5" />
        <div className="rounded-2xl rounded-tl-sm border bg-card px-4 py-3">
          <div className="flex gap-1 items-center h-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="w-1.5 h-1.5 rounded-full" />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export function ChatSkeleton() {
  return (
    <div className="flex h-full">
      <SidebarSkeleton />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Context bar */}
        <div className="flex items-center gap-2 px-4 py-2 border-b bg-background">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-6 w-28 rounded-full" />
        </div>

        <MessagesSkeleton />

        {/* Input area */}
        <div className="px-6 py-4 border-t bg-background">
          <Skeleton className="h-11 w-full rounded-xl" />
          <div className="flex justify-center mt-2">
            <Skeleton className="h-3 w-56" />
          </div>
        </div>
      </div>
    </div>
  )
}
