import { FileText } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn, formatFileSize, formatRelativeTime } from '@/lib/utils'
import { getDocumentFileUrl } from '@/services/api'
import type { Document } from '@/types'

const TYPE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  pdf:  { bg: 'bg-red-100 dark:bg-red-900/20',   text: 'text-red-600 dark:text-red-400',   label: 'PDF'  },
  docx: { bg: 'bg-blue-100 dark:bg-blue-900/20', text: 'text-blue-600 dark:text-blue-400', label: 'DOCX' },
  xlsx: { bg: 'bg-green-100 dark:bg-green-900/20', text: 'text-green-600 dark:text-green-400', label: 'XLSX' },
  txt:  { bg: 'bg-gray-100 dark:bg-gray-900/20', text: 'text-gray-600 dark:text-gray-400', label: 'TXT'  },
}

const TYPE_BADGE_VARIANT: Record<string, string> = {
  pdf:  'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  docx: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  xlsx: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  txt:  'bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-400',
}

interface DocumentRowProps {
  doc: Document
}

export function DocumentRow({ doc }: DocumentRowProps) {
  const style = TYPE_STYLES[doc.type] ?? TYPE_STYLES.txt
  const badgeColor = TYPE_BADGE_VARIANT[doc.type] ?? TYPE_BADGE_VARIANT.txt

  return (
    <a
      href={getDocumentFileUrl(doc.id)}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        'flex items-center gap-4 px-6 py-3 group',
        'hover:bg-muted/40 transition-colors cursor-pointer',
      )}
    >
      {/* File icon */}
      <div className={cn(
        'w-9 h-9 rounded-md flex items-center justify-center shrink-0 transition-transform group-hover:scale-105',
        style.bg,
      )}>
        <FileText className={cn('w-4 h-4', style.text)} />
      </div>

      {/* Name + meta */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate group-hover:text-primary transition-colors">
          {doc.name}
        </p>
        <p className="text-xs text-muted-foreground mt-0.5">
          {doc.folder_name ?? 'No folder'}
          {doc.size ? ` · ${formatFileSize(doc.size)}` : ''}
        </p>
      </div>

      {/* Right meta */}
      <div className="flex items-center gap-2 shrink-0">
        {/* File type badge */}
        <span className={cn(
          'text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide',
          badgeColor,
        )}>
          {style.label}
        </span>

        {/* Index status */}
        <Badge
          variant={doc.indexed ? 'success' : 'warning'}
          className="text-[10px] px-1.5 py-0"
        >
          {doc.indexed ? 'Indexed' : 'Pending'}
        </Badge>

        {/* Relative time */}
        <span className="text-xs text-muted-foreground w-16 text-right">
          {formatRelativeTime(doc.uploaded_at)}
        </span>
      </div>
    </a>
  )
}
