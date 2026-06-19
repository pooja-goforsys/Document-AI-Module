import { CheckCircle2, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { FileUploadCard, type FileUploadState } from './FileUploadCard'

interface UploadProgressProps {
  uploads: FileUploadState[]
  onRemove: (id: string) => void
  className?: string
}

export function UploadProgress({ uploads, onRemove, className }: UploadProgressProps) {
  if (uploads.length === 0) return null

  const active    = uploads.filter(u => u.status === 'uploading' || u.status === 'processing')
  const completed = uploads.filter(u => u.status === 'completed').length
  const failed    = uploads.filter(u => u.status === 'failed').length
  const total     = uploads.length

  return (
    <div className={cn('space-y-3', className)}>
      {/* Summary bar */}
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        {active.length > 0 ? (
          <>
            <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
            <span>
              Uploading {active.length} of {total} file{total > 1 ? 's' : ''}
              {completed > 0 && <span className="text-emerald-600 dark:text-emerald-400"> · {completed} done</span>}
              {failed > 0 && <span className="text-destructive"> · {failed} failed</span>}
            </span>
          </>
        ) : (
          <>
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
            <span>
              {completed > 0 && <span className="text-emerald-600 dark:text-emerald-400">{completed} uploaded</span>}
              {failed > 0 && <span className="text-destructive"> · {failed} failed</span>}
            </span>
          </>
        )}
      </div>

      {/* Per-file cards */}
      <div className="space-y-2 max-h-72 overflow-y-auto pr-0.5">
        {uploads.map(item => (
          <FileUploadCard key={item.id} item={item} onRemove={onRemove} />
        ))}
      </div>
    </div>
  )
}
