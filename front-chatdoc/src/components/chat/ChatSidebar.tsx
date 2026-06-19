import { useState } from 'react'
import { Plus, MessageSquare, Pin, ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { ChatHistoryItem } from './ChatHistoryItem'
import type { ChatSession } from '@/types'

function getSavedCollapsed(): boolean {
  try { return localStorage.getItem('chat-sidebar-collapsed') === 'true' } catch { return false }
}

interface ChatSidebarProps {
  sessions: ChatSession[]
  activeId: string
  onSelectSession: (id: string) => void
  onNewSession: () => void
  onDeleteSession: (id: string) => void
  onRenameSession: (id: string, title: string) => void
  onPinSession: (id: string) => void
}

export function ChatSidebar({
  sessions,
  activeId,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  onRenameSession,
  onPinSession,
}: ChatSidebarProps) {
  const [collapsed, setCollapsed] = useState<boolean>(getSavedCollapsed)

  function toggleCollapsed() {
    setCollapsed(prev => {
      const next = !prev
      try { localStorage.setItem('chat-sidebar-collapsed', String(next)) } catch {}
      return next
    })
  }

  const pinned   = sessions.filter(s => s.pinned)
  const unpinned = sessions.filter(s => !s.pinned)

  return (
    <TooltipProvider delayDuration={200}>
      <aside className={cn(
        'relative flex flex-col h-full bg-background border-r shrink-0',
        'transition-[width] duration-300 ease-in-out',
        collapsed ? 'w-14' : 'w-56',
      )}>
        {/* Header */}
        <div className={cn(
          'flex items-center border-b shrink-0 h-12 px-3',
          collapsed ? 'justify-center' : 'justify-between px-4',
        )}>
          <span className={cn(
            'text-sm font-semibold whitespace-nowrap',
            'transition-[opacity,max-width] duration-300 overflow-hidden',
            collapsed ? 'opacity-0 max-w-0' : 'opacity-100 max-w-[120px]',
          )}>
            Chats
          </span>

          {collapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onNewSession}>
                  <Plus className="w-4 h-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">New chat</TooltipContent>
            </Tooltip>
          ) : (
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onNewSession} title="New chat">
              <Plus className="w-4 h-4" />
            </Button>
          )}
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {collapsed ? (
            sessions.map(session => (
              <Tooltip key={session.id}>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => onSelectSession(session.id)}
                    className={cn(
                      'w-full flex items-center justify-center p-2 rounded-md transition-colors',
                      session.id === activeId ? 'bg-primary text-white' : 'hover:bg-muted',
                    )}
                  >
                    {session.pinned
                      ? <Pin         className="w-4 h-4 shrink-0" />
                      : <MessageSquare className="w-4 h-4 shrink-0" />
                    }
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right" className="max-w-[200px] text-xs">
                  {session.title}
                </TooltipContent>
              </Tooltip>
            ))
          ) : (
            <>
              {/* Pinned section */}
              {pinned.length > 0 && (
                <>
                  <p className="px-2 pt-1 pb-0.5 text-[10px] uppercase tracking-wider text-muted-foreground/60 font-semibold flex items-center gap-1">
                    <Pin className="w-2.5 h-2.5" /> Pinned
                  </p>
                  {pinned.map(session => (
                    <ChatHistoryItem
                      key={session.id}
                      session={session}
                      active={session.id === activeId}
                      onSelect={() => onSelectSession(session.id)}
                      onDelete={() => onDeleteSession(session.id)}
                      onRename={onRenameSession}
                      onPin={onPinSession}
                    />
                  ))}
                  {unpinned.length > 0 && (
                    <p className="px-2 pt-2 pb-0.5 text-[10px] uppercase tracking-wider text-muted-foreground/60 font-semibold">
                      Recent
                    </p>
                  )}
                </>
              )}

              {/* Unpinned sessions */}
              {unpinned.map(session => (
                <ChatHistoryItem
                  key={session.id}
                  session={session}
                  active={session.id === activeId}
                  onSelect={() => onSelectSession(session.id)}
                  onDelete={() => onDeleteSession(session.id)}
                  onRename={onRenameSession}
                  onPin={onPinSession}
                />
              ))}
            </>
          )}
        </div>

        {/* Collapse toggle */}
        <button
          onClick={toggleCollapsed}
          className="absolute -right-3 top-14 w-6 h-6 rounded-full bg-background border border-border flex items-center justify-center hover:bg-accent transition-colors z-10 shadow-sm"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed
            ? <ChevronRight className="w-3 h-3" />
            : <ChevronLeft  className="w-3 h-3" />
          }
        </button>
      </aside>
    </TooltipProvider>
  )
}
