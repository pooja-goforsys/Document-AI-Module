import { FileText, Search } from 'lucide-react'
import type { SelectionDocument, ChatScope } from '@/types'
import { cn } from '@/lib/utils'

interface DocumentSelectorProps {
  message: string
  documents: SelectionDocument[]
  onSelect: (scope: ChatScope) => void
  onSearchAll: () => void
  disabled?: boolean
}

export function DocumentSelector({
  message,
  documents,
  onSelect,
  onSearchAll,
  disabled,
}: DocumentSelectorProps) {
  return (
    <div className="space-y-3 py-1">
      <p className="text-sm text-foreground/80">{message}</p>

      <div className="space-y-2">
        {documents.map((doc) => (
          <button
            key={doc.id}
            onClick={() => onSelect({ type: 'document', id: doc.id, name: doc.name })}
            disabled={disabled}
            className={cn(
              'w-full flex items-center justify-between gap-3 px-4 py-3',
              'rounded-lg border border-border bg-background',
              'hover:border-primary/60 hover:bg-primary/5',
              'transition-colors text-left',
              'disabled:opacity-50 disabled:cursor-not-allowed',
            )}
          >
            <div className="flex items-center gap-2 min-w-0">
              <FileText className="w-4 h-4 text-muted-foreground shrink-0" />
              <span className="text-sm font-medium truncate">{doc.name}</span>
            </div>
            {doc.similarity != null && (
              <span className="text-xs text-muted-foreground shrink-0 tabular-nums">
                {Math.round(doc.similarity * 100)}% match
              </span>
            )}
          </button>
        ))}
      </div>

      <button
        onClick={onSearchAll}
        disabled={disabled}
        className={cn(
          'w-full flex items-center justify-center gap-2 px-4 py-2.5',
          'rounded-lg border border-dashed border-muted-foreground/40',
          'hover:border-muted-foreground/70 hover:bg-muted/30',
          'transition-colors text-sm text-muted-foreground',
          'disabled:opacity-50 disabled:cursor-not-allowed',
        )}
      >
        <Search className="w-3.5 h-3.5" />
        Search across all documents
      </button>
    </div>
  )
}
