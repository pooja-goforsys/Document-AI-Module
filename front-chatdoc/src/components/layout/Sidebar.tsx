import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  FolderOpen,
  MessageSquare,
  Bell,
  Bot,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useState } from 'react'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

const navItems = [
  { to: '/dashboard',     label: 'Dashboard',     icon: LayoutDashboard, preload: () => import('@/pages/Dashboard/DashboardPage') },
  { to: '/documents',     label: 'Documents',     icon: FolderOpen,      preload: () => import('@/pages/Documents/DocumentsPage') },
  { to: '/chat',          label: 'AI Chat',       icon: MessageSquare,   preload: () => import('@/pages/Chat/ChatPage') },
  { to: '/notifications', label: 'Notifications', icon: Bell,            preload: () => import('@/pages/Notifications/NotificationsPage') },
]

function getSavedCollapsed(): boolean {
  try { return localStorage.getItem('sidebar-collapsed') === 'true' } catch { return false }
}

export function Sidebar() {
  const [collapsed, setCollapsed] = useState<boolean>(getSavedCollapsed)
  const location = useLocation()

  function toggleCollapsed() {
    setCollapsed(prev => {
      const next = !prev
      try { localStorage.setItem('sidebar-collapsed', String(next)) } catch {}
      return next
    })
  }

  return (
    <TooltipProvider delayDuration={200}>
      <aside
        className={cn(
          'relative flex flex-col h-screen bg-sidebar text-sidebar-foreground border-r border-sidebar-accent shrink-0',
          'transition-[width] duration-300 ease-in-out',
          collapsed ? 'w-16' : 'w-60',
        )}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 h-16 border-b border-sidebar-accent shrink-0 overflow-hidden">
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary shrink-0">
            <Bot className="w-5 h-5 text-white" />
          </div>
          <span
            className={cn(
              'font-semibold text-sm tracking-tight text-sidebar-foreground whitespace-nowrap',
              'transition-[opacity,max-width] duration-300',
              collapsed ? 'opacity-0 max-w-0 overflow-hidden' : 'opacity-100 max-w-[160px]',
            )}
          >
            DocAI Platform
          </span>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
          {navItems.map(({ to, label, icon: Icon, preload }) => {
            const active = location.pathname.startsWith(to)
            const linkEl = (
              <NavLink
                key={to}
                to={to}
                onFocus={preload}
                onPointerEnter={preload}
                className={cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors',
                  collapsed ? 'justify-center' : '',
                  active
                    ? 'bg-primary text-white'
                    : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground',
                )}
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span
                  className={cn(
                    'truncate transition-[opacity,max-width] duration-300',
                    collapsed ? 'opacity-0 max-w-0 overflow-hidden' : 'opacity-100 max-w-[140px]',
                  )}
                >
                  {label}
                </span>
              </NavLink>
            )

            if (!collapsed) return linkEl

            return (
              <Tooltip key={to}>
                <TooltipTrigger asChild>{linkEl}</TooltipTrigger>
                <TooltipContent side="right">{label}</TooltipContent>
              </Tooltip>
            )
          })}
        </nav>

        {/* User area */}
        <div
          className={cn(
            'px-4 py-4 border-t border-sidebar-accent shrink-0 overflow-hidden',
            'transition-[opacity,max-height] duration-300',
            collapsed ? 'opacity-0 max-h-0 py-0 border-t-0' : 'opacity-100 max-h-24',
          )}
        >
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center shrink-0">
              <span className="text-xs font-semibold text-primary">PG</span>
            </div>
            <div className="min-w-0">
              <p className="text-xs font-medium truncate">Pooja Goforsys</p>
              <p className="text-xs text-sidebar-foreground/50 truncate">developer@goforsys.com</p>
            </div>
          </div>
        </div>

        {/* Collapse toggle */}
        <button
          onClick={toggleCollapsed}
          className="absolute -right-3 top-20 w-6 h-6 rounded-full bg-background border border-border flex items-center justify-center hover:bg-accent transition-colors z-10 shadow-sm"
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
