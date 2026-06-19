import { useState, useRef, useEffect } from 'react'
import { Globe, Folder, FileText, Trash2, Pin, PinOff, Pencil, Check, X } from 'lucide-react'
import { cn, formatRelativeTime } from '@/lib/utils'
import type { ChatSession } from '@/types'

const SCOPE_ICON = {
  all:      { Icon: Globe,     color: 'text-blue-500',   bg: 'bg-blue-100 dark:bg-blue-900/30'     },
  folder:   { Icon: Folder,    color: 'text-violet-500', bg: 'bg-violet-100 dark:bg-violet-900/30' },
  document: { Icon: FileText,  color: 'text-orange-500', bg: 'bg-orange-100 dark:bg-orange-900/30' },
}

interface ChatHistoryItemProps {
  session: ChatSession
  active: boolean
  onSelect: () => void
  onDelete: () => void
  onRename: (id: string, title: string) => void
  onPin: (id: string) => void
}

export function ChatHistoryItem({
  session, active, onSelect, onDelete, onRename, onPin,
}: ChatHistoryItemProps) {
  const scopeKey = session.scope.type
  const { Icon, color, bg } = SCOPE_ICON[scopeKey] ?? SCOPE_ICON.all

  const [editing, setEditing]   = useState(false)
  const [draft,   setDraft]     = useState(session.title)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) {
      setDraft(session.title)
      setTimeout(() => inputRef.current?.select(), 10)
    }
  }, [editing, session.title])

  function commitRename() {
    const t = draft.trim()
    if (t && t !== session.title) onRename(session.id, t)
    setEditing(false)
  }

  function cancelEdit(e?: React.KeyboardEvent) {
    if (e) e.stopPropagation()
    setEditing(false)
    setDraft(session.title)
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => !editing && onSelect()}
      onKeyDown={e => !editing && e.key === 'Enter' && onSelect()}
      onDoubleClick={e => { e.preventDefault(); setEditing(true) }}
      className={cn(
        'flex items-center gap-2 px-3 py-2 rounded-md cursor-pointer group transition-colors relative',
        active ? 'bg-primary text-white' : 'hover:bg-muted',
      )}
    >
      {/* Scope icon */}
      <div className={cn(
        'w-6 h-6 rounded-md flex items-center justify-center shrink-0',
        active ? 'bg-white/20' : bg,
      )}>
        <Icon className={cn('w-3 h-3', active ? 'text-white' : color)} />
      </div>

      {/* Title / edit input */}
      <div className="flex-1 min-w-0">
        {editing ? (
          <input
            ref={inputRef}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter')  { e.preventDefault(); commitRename() }
              if (e.key === 'Escape') { cancelEdit(e) }
            }}
            onBlur={commitRename}
            onClick={e => e.stopPropagation()}
            className="w-full bg-transparent text-xs font-medium outline-none border-b border-primary/50 pb-0.5"
          />
        ) : (
          <>
            <div className="flex items-center gap-1 min-w-0">
              {session.pinned && (
                <Pin className={cn('w-2.5 h-2.5 shrink-0', active ? 'text-white/60' : 'text-primary/60')} />
              )}
              <p className="text-xs font-medium truncate">{session.title}</p>
            </div>
            <p className={cn(
              'text-[10px] truncate transition-colors',
              active ? 'text-white/60' : 'text-muted-foreground',
            )}>
              {session.scope.type !== 'all' && session.scope.name
                ? session.scope.name
                : formatRelativeTime(session.updated_at)
              }
            </p>
          </>
        )}
      </div>

      {/* Action buttons — shown on hover when not editing */}
      {!editing && (
        <div className={cn(
          'flex items-center gap-0.5 shrink-0',
          'opacity-0 group-hover:opacity-100 transition-opacity',
        )}>
          <button
            className={cn('p-0.5 rounded', active ? 'hover:bg-white/20' : 'hover:bg-muted-foreground/20')}
            onClick={e => { e.stopPropagation(); setEditing(true) }}
            title="Rename"
          >
            <Pencil className="w-3 h-3" />
          </button>
          <button
            className={cn('p-0.5 rounded', active ? 'hover:bg-white/20' : 'hover:bg-muted-foreground/20')}
            onClick={e => { e.stopPropagation(); onPin(session.id) }}
            title={session.pinned ? 'Unpin' : 'Pin'}
          >
            {session.pinned
              ? <PinOff className="w-3 h-3" />
              : <Pin    className="w-3 h-3" />
            }
          </button>
          <button
            className={cn('p-0.5 rounded', active ? 'hover:bg-white/20' : 'hover:bg-muted-foreground/20')}
            onClick={e => { e.stopPropagation(); onDelete() }}
            title="Delete chat"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* Confirm / cancel inline edit */}
      {editing && (
        <div className="flex items-center gap-0.5 shrink-0">
          <button
            className="p-0.5 rounded hover:bg-green-500/20"
            onMouseDown={e => { e.preventDefault(); commitRename() }}
            title="Save"
          >
            <Check className="w-3 h-3 text-green-500" />
          </button>
          <button
            className="p-0.5 rounded hover:bg-red-500/20"
            onMouseDown={e => { e.preventDefault(); cancelEdit() }}
            title="Cancel"
          >
            <X className="w-3 h-3 text-red-400" />
          </button>
        </div>
      )}
    </div>
  )
}
