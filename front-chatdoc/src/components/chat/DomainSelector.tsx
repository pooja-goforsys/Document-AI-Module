import { Search } from 'lucide-react'
import type { SelectionDomain } from '@/types'
import { cn } from '@/lib/utils'

// Deterministic color palette — index driven by a hash of the domain name
const PALETTE = [
  { bg: 'bg-blue-500/10',    border: 'border-blue-400/40',    dot: 'bg-blue-500',    label: 'text-blue-700 dark:text-blue-300'   },
  { bg: 'bg-emerald-500/10', border: 'border-emerald-400/40', dot: 'bg-emerald-500', label: 'text-emerald-700 dark:text-emerald-300' },
  { bg: 'bg-violet-500/10',  border: 'border-violet-400/40',  dot: 'bg-violet-500',  label: 'text-violet-700 dark:text-violet-300'  },
  { bg: 'bg-amber-500/10',   border: 'border-amber-400/40',   dot: 'bg-amber-500',   label: 'text-amber-700 dark:text-amber-300'   },
  { bg: 'bg-rose-500/10',    border: 'border-rose-400/40',    dot: 'bg-rose-500',    label: 'text-rose-700 dark:text-rose-300'     },
  { bg: 'bg-cyan-500/10',    border: 'border-cyan-400/40',    dot: 'bg-cyan-500',    label: 'text-cyan-700 dark:text-cyan-300'     },
  { bg: 'bg-indigo-500/10',  border: 'border-indigo-400/40',  dot: 'bg-indigo-500',  label: 'text-indigo-700 dark:text-indigo-300' },
  { bg: 'bg-teal-500/10',    border: 'border-teal-400/40',    dot: 'bg-teal-500',    label: 'text-teal-700 dark:text-teal-300'    },
  { bg: 'bg-orange-500/10',  border: 'border-orange-400/40',  dot: 'bg-orange-500',  label: 'text-orange-700 dark:text-orange-300' },
  { bg: 'bg-pink-500/10',    border: 'border-pink-400/40',    dot: 'bg-pink-500',    label: 'text-pink-700 dark:text-pink-300'    },
]

function colorFor(name: string) {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) & 0x7fffffff
  }
  return PALETTE[hash % PALETTE.length]
}

interface DomainSelectorProps {
  message: string
  domains: SelectionDomain[]
  onSelect: (domainName: string) => void
  onSearchAll: () => void
  disabled?: boolean
}

export function DomainSelector({
  message,
  domains,
  onSelect,
  onSearchAll,
  disabled,
}: DomainSelectorProps) {
  return (
    <div className="space-y-3 py-1 min-w-[260px]">
      <p className="text-sm text-foreground/80 leading-snug">{message}</p>

      <div className="space-y-2">
        {domains.map((domain) => {
          const c = colorFor(domain.domain_name)
          return (
            <button
              key={domain.domain_name}
              onClick={() => onSelect(domain.domain_name)}
              disabled={disabled}
              className={cn(
                'w-full flex items-center justify-between gap-3 px-4 py-3',
                'rounded-xl border transition-all text-left',
                'hover:scale-[1.01] active:scale-[0.99]',
                'disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100',
                c.bg, c.border,
              )}
            >
              <div className="flex items-center gap-3 min-w-0">
                <span className={cn('w-3 h-3 rounded-full shrink-0 ring-2 ring-white/30', c.dot)} />
                <div className="min-w-0">
                  <p className={cn('text-sm font-semibold leading-none truncate', c.label)}>
                    {domain.domain_name}
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {domain.document_count} document{domain.document_count !== 1 ? 's' : ''}
                  </p>
                </div>
              </div>
              <span className="text-xs text-muted-foreground/70 shrink-0 tabular-nums">
                {Math.round(domain.similarity * 100)}%
              </span>
            </button>
          )
        })}
      </div>

      <button
        onClick={onSearchAll}
        disabled={disabled}
        className={cn(
          'w-full flex items-center justify-center gap-2 px-4 py-2.5',
          'rounded-xl border border-dashed border-muted-foreground/35',
          'hover:border-muted-foreground/60 hover:bg-muted/40',
          'transition-colors text-sm text-muted-foreground',
          'disabled:opacity-50 disabled:cursor-not-allowed',
        )}
      >
        <Search className="w-3.5 h-3.5" />
        Search across all domains
      </button>
    </div>
  )
}
