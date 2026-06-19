import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { getFolders, getDocuments } from '@/services/api'
import { ChevronDown, Globe, Folder, FileText, BookOpen, Check, Lock } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ChatScope } from '@/types'

const FILE_TYPE_COLORS: Record<string, string> = {
  pdf:  'text-red-500',
  docx: 'text-blue-500',
  xlsx: 'text-green-500',
  txt:  'text-gray-500',
}

interface ContextSelectorProps {
  value: ChatScope
  onChange: (scope: ChatScope) => void
  locked?: boolean     // true once session has messages — scope cannot change
}

export function ContextSelector({ value, onChange, locked = false }: ContextSelectorProps) {
  const [open, setOpen] = useState(false)

  const { data: folders = [] } = useQuery({
    queryKey: ['folders'],
    queryFn: getFolders,
  })

  const { data: allDocs = [] } = useQuery({
    queryKey: ['documents'],
    queryFn: () => getDocuments(),
  })

  const indexedDocs = allDocs.filter(d => d.indexed)

  // Annotate each folder with its indexed document count
  const foldersWithCount = folders.map(f => ({
    ...f,
    indexedCount: indexedDocs.filter(d => d.folder_id === f.id).length,
  }))

  const label =
    value.type === 'all'      ? 'All Documents'  :
    value.type === 'domain'   ? (value.name ?? 'Domain') :
    (value.name ?? (value.type === 'folder' ? 'Folder' : 'Document'))

  const ScopeIcon =
    value.type === 'folder'   ? Folder   :
    value.type === 'document' ? FileText :
    value.type === 'domain'   ? BookOpen :
    Globe

  const iconColor =
    value.type === 'folder'   ? 'text-violet-300' :
    value.type === 'document' ? 'text-orange-300' :
    value.type === 'domain'   ? 'text-emerald-300':
    'text-blue-300'

  return (
    <DropdownMenu.Root
      open={open && !locked}
      onOpenChange={v => { if (!locked) setOpen(v) }}
    >
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          disabled={locked}
          aria-label={locked ? `Context locked: ${label}` : `Select context: ${label}`}
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium',
            'border border-primary bg-primary text-white',
            'transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            locked
              ? 'opacity-90 cursor-default'
              : 'hover:bg-primary/85 cursor-pointer',
          )}
        >
          <ScopeIcon className={cn('w-3 h-3 shrink-0', iconColor)} />
          <span className="max-w-[140px] truncate">{label}</span>
          {locked
            ? <Lock className="w-2.5 h-2.5 opacity-60 shrink-0" />
            : <ChevronDown className={cn('w-3 h-3 shrink-0 transition-transform duration-150', open && 'rotate-180')} />
          }
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          sideOffset={6}
          align="start"
          className={cn(
            'z-50 w-72 rounded-lg border bg-popover text-popover-foreground shadow-lg',
            'p-1 outline-none',
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
            'data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
            'data-[side=bottom]:slide-in-from-top-2',
          )}
        >
          {/* Section header */}
          <p className="px-2 pt-1 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Chat context
          </p>

          {/* All Documents */}
          <DropdownMenu.Item
            onSelect={() => onChange({ type: 'all', id: null, name: null })}
            className="flex items-center gap-2.5 px-2 py-2 text-sm rounded-md cursor-pointer outline-none hover:bg-accent hover:text-accent-foreground data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground"
          >
            <div className="w-7 h-7 rounded-md bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center shrink-0">
              <Globe className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-medium text-xs">All Documents</div>
              <div className="text-xs text-muted-foreground">
                {indexedDocs.length} indexed document{indexedDocs.length !== 1 ? 's' : ''}
              </div>
            </div>
            {value.type === 'all' && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
          </DropdownMenu.Item>

          {/* Folders */}
          {foldersWithCount.length > 0 && (
            <>
              <DropdownMenu.Separator className="my-1 -mx-1 h-px bg-border" />
              <p className="px-2 pt-1 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Folders
              </p>
              {foldersWithCount.map(folder => {
                const active = value.type === 'folder' && value.id === folder.id
                return (
                  <DropdownMenu.Item
                    key={folder.id}
                    disabled={folder.indexedCount === 0}
                    onSelect={() => {
                      if (folder.indexedCount > 0) {
                        onChange({ type: 'folder', id: folder.id, name: folder.name })
                      }
                    }}
                    className={cn(
                      'flex items-center gap-2.5 px-2 py-2 text-sm rounded-md outline-none',
                      'hover:bg-accent hover:text-accent-foreground',
                      'data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground',
                      folder.indexedCount === 0
                        ? 'opacity-40 cursor-not-allowed data-[highlighted]:bg-transparent data-[highlighted]:text-current'
                        : 'cursor-pointer',
                    )}
                  >
                    <div className="w-7 h-7 rounded-md bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center shrink-0">
                      <Folder className="w-3.5 h-3.5 text-violet-600 dark:text-violet-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-xs truncate">{folder.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {folder.indexedCount === 0
                          ? 'No indexed documents'
                          : `${folder.indexedCount} indexed`}
                      </div>
                    </div>
                    {active && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
                  </DropdownMenu.Item>
                )
              })}
            </>
          )}

          {/* Documents */}
          {indexedDocs.length > 0 && (
            <>
              <DropdownMenu.Separator className="my-1 -mx-1 h-px bg-border" />
              <p className="px-2 pt-1 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Documents
              </p>
              {indexedDocs.slice(0, 12).map(doc => {
                const active = value.type === 'document' && value.id === doc.id
                return (
                  <DropdownMenu.Item
                    key={doc.id}
                    onSelect={() => onChange({ type: 'document', id: doc.id, name: doc.name })}
                    className="flex items-center gap-2.5 px-2 py-2 text-sm rounded-md cursor-pointer outline-none hover:bg-accent hover:text-accent-foreground data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground"
                  >
                    <div className="w-7 h-7 rounded-md bg-orange-100 dark:bg-orange-900/30 flex items-center justify-center shrink-0">
                      <FileText className={cn('w-3.5 h-3.5', FILE_TYPE_COLORS[doc.type] ?? 'text-orange-500')} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-xs truncate">{doc.name}</div>
                      <div className="text-xs text-muted-foreground truncate">
                        {doc.folder_name ? `📁 ${doc.folder_name}` : 'No folder'} · {doc.type.toUpperCase()}
                      </div>
                    </div>
                    {active && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
                  </DropdownMenu.Item>
                )
              })}
              {indexedDocs.length > 12 && (
                <p className="px-2 py-1.5 text-[10px] text-muted-foreground text-center">
                  +{indexedDocs.length - 12} more — browse in Documents
                </p>
              )}
            </>
          )}

          {indexedDocs.length === 0 && folders.length === 0 && (
            <p className="px-2 py-3 text-xs text-muted-foreground text-center">
              No indexed documents yet. Upload and index files first.
            </p>
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
