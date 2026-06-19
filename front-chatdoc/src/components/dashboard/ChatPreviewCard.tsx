import { useNavigate } from 'react-router-dom'
import { MessageSquare, Clock, Pin, FileText, Folder, Globe, ChevronRight } from 'lucide-react'
import { cn, formatRelativeTime } from '@/lib/utils'
import type { BackendSession } from '@/services/api'

interface ChatPreviewCardProps {
  session: BackendSession
}

const SCOPE_ICON: Record<string, React.ElementType> = {
  folder:   Folder,
  document: FileText,
  domain:   Globe,
  all:      Globe,
}

const SCOPE_LABEL: Record<string, string> = {
  folder:   'Folder',
  document: 'Document',
  domain:   'Domain',
  all:      'All docs',
}

export function ChatPreviewCard({ session }: ChatPreviewCardProps) {
  const navigate = useNavigate()
  const ScopeIcon = SCOPE_ICON[session.scope_type] ?? Globe
  const scopeLabel = session.scope_name ?? SCOPE_LABEL[session.scope_type] ?? 'All docs'

  return (
    <button
      type="button"
      onClick={() => navigate('/chat', { state: { sessionId: session.id } })}
      className={cn(
        'w-full text-left flex items-start gap-3 px-4 py-3.5 group',
        'hover:bg-muted/50 active:bg-muted/70 transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40',
      )}
    >
      {/* Avatar */}
      <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5 group-hover:bg-primary/20 transition-colors">
        <MessageSquare className="w-4 h-4 text-primary" />
      </div>

      {/* Body */}
      <div className="flex-1 min-w-0 space-y-1">

        {/* Title row */}
        <div className="flex items-center gap-1.5 min-w-0">
          {session.pinned && (
            <Pin className="w-3 h-3 text-amber-500 shrink-0 fill-amber-500" />
          )}
          <p className="text-sm font-semibold truncate group-hover:text-primary transition-colors leading-tight">
            {session.title || 'Untitled Chat'}
          </p>
        </div>

        {/* Last message preview */}
        {session.last_message_preview && (
          <p className="text-xs text-muted-foreground line-clamp-2 leading-snug">
            {session.last_message_preview}
          </p>
        )}

        {/* Meta row */}
        <div className="flex items-center gap-2.5 flex-wrap pt-0.5">
          {/* Scope badge */}
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground/70 bg-muted/60 rounded px-1.5 py-0.5">
            <ScopeIcon className="w-2.5 h-2.5" />
            <span className="truncate max-w-[100px]">{scopeLabel}</span>
          </span>

          {/* Timestamp */}
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Clock className="w-2.5 h-2.5" />
            {formatRelativeTime(session.updated_at)}
          </span>

          {/* Message count */}
          <span className="text-xs text-muted-foreground/60">
            {session.message_count} msg{session.message_count !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      {/* Chevron */}
      <ChevronRight className="w-4 h-4 text-muted-foreground/40 shrink-0 mt-2 group-hover:text-primary/60 group-hover:translate-x-0.5 transition-all" />
    </button>
  )
}
