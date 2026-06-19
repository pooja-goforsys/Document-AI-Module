import { Skeleton } from '@/components/ui/skeleton'

function FoldersSkeleton() {
  return (
    <div className="p-2 space-y-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-center gap-2.5 px-3 py-2">
          <Skeleton className="w-4 h-4 rounded shrink-0" />
          <Skeleton className="h-3.5 flex-1" />
          <Skeleton className="h-3 w-5 shrink-0" />
        </div>
      ))}
    </div>
  )
}

function DocumentListSkeleton() {
  return (
    <div className="divide-y">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 px-6 py-3">
          <Skeleton className="w-8 h-8 rounded-md shrink-0" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-2/3" />
            <Skeleton className="h-3 w-1/3" />
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <Skeleton className="h-5 w-14 rounded-full" />
            <Skeleton className="h-5 w-16 rounded-full" />
            <Skeleton className="h-7 w-7 rounded" />
            <Skeleton className="h-7 w-7 rounded" />
          </div>
        </div>
      ))}
    </div>
  )
}

export function DocumentsSkeleton() {
  return (
    <div className="flex h-full">
      {/* Folder sidebar skeleton */}
      <aside className="w-56 shrink-0 border-r bg-background flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <Skeleton className="h-4 w-14" />
          <Skeleton className="h-7 w-7 rounded" />
        </div>
        <FoldersSkeleton />
      </aside>

      {/* Main skeleton */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center gap-3 px-6 py-3 border-b bg-background">
          <Skeleton className="h-4 w-24" />
          <div className="flex-1" />
          <Skeleton className="h-8 w-48 rounded-md" />
          <Skeleton className="h-8 w-20 rounded-md" />
          <Skeleton className="h-9 w-28 rounded-md" />
        </div>
        <DocumentListSkeleton />
      </div>
    </div>
  )
}
