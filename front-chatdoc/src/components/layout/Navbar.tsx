import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import {
  Moon, Sun, Monitor, ChevronRight,
  LogOut, User, ChevronDown,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { Button } from '@/components/ui/button'
import { useTheme, type Theme } from '@/hooks/useTheme'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/lib/utils'
import { NotificationBell } from '@/components/notifications/NotificationBell'

// ─── Breadcrumb map ────────────────────────────────────────────────────────────

const breadcrumbMap: Record<string, string[]> = {
  '/dashboard':     ['Dashboard'],
  '/documents':     ['Documents'],
  '/chat':          ['AI Chat'],
  '/notifications': ['Notifications'],
}

// ─── Theme toggle ──────────────────────────────────────────────────────────────

const THEME_OPTIONS: { value: Theme; label: string; icon: React.ElementType }[] = [
  { value: 'light',  label: 'Light',  icon: Sun     },
  { value: 'dark',   label: 'Dark',   icon: Moon    },
  { value: 'system', label: 'System', icon: Monitor },
]

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const current = THEME_OPTIONS.find(o => o.value === theme) ?? THEME_OPTIONS[2]
  const Icon = current.icon

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="ghost" size="icon"
        onClick={() => setOpen(o => !o)}
        title={`Theme: ${current.label}`}
        aria-label="Toggle theme"
      >
        <Icon className="w-4 h-4 transition-transform duration-200" />
      </Button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 w-36 rounded-lg border bg-popover shadow-lg z-50 py-1 overflow-hidden animate-in fade-in-0 zoom-in-95 duration-100">
          {THEME_OPTIONS.map(({ value, label, icon: OptionIcon }) => (
            <button
              key={value}
              className={cn(
                'w-full flex items-center gap-2.5 px-3 py-2 text-sm transition-colors text-left hover:bg-muted',
                theme === value ? 'text-primary font-medium bg-primary/5' : 'text-foreground',
              )}
              onClick={() => { setTheme(value); setOpen(false) }}
            >
              <OptionIcon className="w-3.5 h-3.5 shrink-0" />
              <span className="flex-1">{label}</span>
              {theme === value && <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── User avatar ───────────────────────────────────────────────────────────────

function getInitials(name: string | null | undefined, email: string): string {
  if (name && name.trim()) {
    const parts = name.trim().split(/\s+/)
    return parts.length >= 2
      ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
      : parts[0].slice(0, 2).toUpperCase()
  }
  return email.slice(0, 2).toUpperCase()
}

function avatarColor(email: string): string {
  const colors = [
    'bg-indigo-500', 'bg-violet-500', 'bg-purple-500', 'bg-pink-500',
    'bg-rose-500', 'bg-orange-500', 'bg-amber-500', 'bg-teal-500',
    'bg-cyan-500', 'bg-sky-500', 'bg-blue-500', 'bg-green-500',
  ]
  let hash = 0
  for (const ch of email) hash = (hash * 31 + ch.charCodeAt(0)) & 0xffff
  return colors[hash % colors.length]
}

// ─── User menu ─────────────────────────────────────────────────────────────────

function UserMenu() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  if (!user) return null

  const initials = getInitials(user.full_name, user.email)
  const color    = avatarColor(user.email)

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className={cn(
          'flex items-center gap-2 px-2 py-1.5 rounded-lg transition-colors',
          'hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        )}
        aria-label="User menu"
      >
        {/* Avatar */}
        <div className={cn(
          'w-7 h-7 rounded-full flex items-center justify-center text-white text-xs font-semibold shrink-0',
          color,
        )}>
          {initials}
        </div>

        {/* Name (hidden on small screens) */}
        <span className="hidden sm:block text-sm font-medium text-foreground max-w-[120px] truncate">
          {user.full_name ?? user.email.split('@')[0]}
        </span>

        <ChevronDown className={cn('w-3.5 h-3.5 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0,   scale: 1    }}
            exit={{    opacity: 0, y: -6,   scale: 0.97 }}
            transition={{ duration: 0.12, ease: 'easeOut' }}
            className="absolute right-0 top-full mt-2 w-64 bg-popover border rounded-xl shadow-lg z-50 overflow-hidden"
          >
            {/* User info header */}
            <div className="px-4 py-3 border-b">
              <div className="flex items-center gap-3">
                <div className={cn(
                  'w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-semibold shrink-0',
                  color,
                )}>
                  {initials}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-foreground truncate">
                    {user.full_name ?? 'User'}
                  </p>
                  <p className="text-xs text-muted-foreground truncate">{user.email}</p>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="p-1">
              <button
                className="w-full flex items-center gap-2.5 px-3 py-2 text-sm rounded-lg text-muted-foreground hover:bg-muted transition-colors"
                onClick={() => setOpen(false)}
              >
                <User className="w-4 h-4 shrink-0" />
                Profile
              </button>

              <button
                className="w-full flex items-center gap-2.5 px-3 py-2 text-sm rounded-lg text-destructive hover:bg-destructive/10 transition-colors"
                onClick={() => { setOpen(false); logout() }}
              >
                <LogOut className="w-4 h-4 shrink-0" />
                Sign out
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ─── Navbar ────────────────────────────────────────────────────────────────────

export function Navbar() {
  const { pathname } = useLocation()
  const crumbs = breadcrumbMap[pathname] ?? [pathname.replace('/', '')]

  return (
    <header className="flex items-center justify-between h-16 px-6 border-b bg-background shrink-0">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1 text-sm">
        <span className="text-muted-foreground">DocAI</span>
        {crumbs.map((crumb, i) => (
          <span key={i} className="flex items-center gap-1">
            <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />
            <span className={i === crumbs.length - 1 ? 'font-medium text-foreground' : 'text-muted-foreground'}>
              {crumb}
            </span>
          </span>
        ))}
      </nav>

      {/* Actions */}
      <div className="flex items-center gap-1">
        <NotificationBell />
        <ThemeToggle />
        <div className="w-px h-5 bg-border mx-1" />
        <UserMenu />
      </div>
    </header>
  )
}
