import { File, X, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react'
import { Progress } from '@/components/ui/progress'
import { cn, formatFileSize } from '@/lib/utils'

export type UploadStatus = 'queued' | 'uploading' | 'processing' | 'completed' | 'failed'

export interface FileUploadState {
  file: File
  id: string
  status: UploadStatus
  progress: number
  error?: string
}

const FILE_TYPE_BG: Record<string, string> = {
  pdf:  'bg-red-100 dark:bg-red-900/20',
  docx: 'bg-blue-100 dark:bg-blue-900/20',
  xlsx: 'bg-green-100 dark:bg-green-900/20',
  txt:  'bg-gray-100 dark:bg-gray-900/20',
}

const FILE_TYPE_TEXT: Record<string, string> = {
  pdf:  'text-red-500',
  docx: 'text-blue-500',
  xlsx: 'text-green-500',
  txt:  'text-gray-500',
}

const STATUS_CONFIG: Record<UploadStatus, { label: string; color: string }> = {
  queued:     { label: 'Queued',     color: 'text-muted-foreground' },
  uploading:  { label: 'Uploading',  color: 'text-blue-500' },
  processing: { label: 'Processing', color: 'text-amber-500' },
  completed:  { label: 'Uploaded',   color: 'text-emerald-500' },
  failed:     { label: 'Failed',     color: 'text-destructive' },
}

function getFileExt(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() ?? 'txt'
}

interface FileUploadCardProps {
  item: FileUploadState
  onRemove?: (id: string) => void
}

export function FileUploadCard({ item, onRemove }: FileUploadCardProps) {
  const ext = getFileExt(item.file.name)
  const { label, color } = STATUS_CONFIG[item.status]
  const canRemove = item.status === 'queued' || item.status === 'completed' || item.status === 'failed'
  const isActive  = item.status === 'uploading' || item.status === 'processing'

  return (
    <div className={cn(
      'flex items-center gap-3 p-3 rounded-lg border bg-background transition-colors',
      item.status === 'completed' && 'border-emerald-200 dark:border-emerald-900/40',
      item.status === 'failed'    && 'border-destructive/30',
    )}>
      {/* File icon */}
      <div className={cn(
        'w-9 h-9 rounded-md flex items-center justify-center shrink-0',
        FILE_TYPE_BG[ext] ?? FILE_TYPE_BG.txt,
      )}>
        <File className={cn('w-4 h-4', FILE_TYPE_TEXT[ext] ?? FILE_TYPE_TEXT.txt)} />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2 mb-1">
          <p className="text-sm font-medium truncate">{item.file.name}</p>
          <span className={cn('text-xs font-medium shrink-0', color)}>
            {item.status === 'uploading' ? `${item.progress}%` : label}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground shrink-0">
            {formatFileSize(item.file.size)}
          </span>

          {item.status === 'uploading' && (
            <Progress value={item.progress} className="h-1.5 flex-1" />
          )}
          {item.status === 'processing' && (
            <Progress className="h-1.5 flex-1" />
          )}
          {item.status === 'failed' && item.error && (
            <p className="text-xs text-destructive truncate flex-1">{item.error}</p>
          )}
        </div>
      </div>

      {/* Status icon / remove */}
      <div className="shrink-0 flex items-center">
        {isActive ? (
          <Loader2 className="w-4 h-4 animate-spin text-primary" />
        ) : item.status === 'completed' ? (
          <CheckCircle2 className="w-4 h-4 text-emerald-500" />
        ) : item.status === 'failed' ? (
          <AlertCircle className="w-4 h-4 text-destructive" />
        ) : null}

        {canRemove && onRemove && (
          <button
            onClick={() => onRemove(item.id)}
            className="ml-1 p-0.5 text-muted-foreground hover:text-foreground transition-colors rounded"
            title="Remove"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}
