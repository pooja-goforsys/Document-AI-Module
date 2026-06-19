import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Bookmark, BookmarkCheck, Plus, Pencil, Trash2,
  Pin, PinOff, ChevronDown, ChevronRight, X, Check,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { savedPromptsApi } from '@/services/api'
import type { SavedPrompt, SavedPromptCreate, ResponseMode } from '@/types'

// ── Types ──────────────────────────────────────────────────────────────────────

interface SavedPromptsPanelProps {
  onUsePrompt: (content: string) => void
  disabled?: boolean
}

// ── Inline edit form ───────────────────────────────────────────────────────────

interface EditFormProps {
  initial?: Pick<SavedPrompt, 'title' | 'content' | 'response_mode' | 'category'>
  onSave: (data: SavedPromptCreate) => void
  onCancel: () => void
  saving?: boolean
}

const RESPONSE_MODES: { value: ResponseMode | ''; label: string }[] = [
  { value: '',          label: 'Auto' },
  { value: 'simple',   label: 'Simple' },
  { value: 'detailed', label: 'Detailed' },
  { value: 'technical',label: 'Technical' },
  { value: 'summary',  label: 'Summary' },
  { value: 'bullets',  label: 'Bullets' },
  { value: 'executive',label: 'Executive' },
]

function EditForm({ initial, onSave, onCancel, saving }: EditFormProps) {
  const [title,        setTitle]        = useState(initial?.title        ?? '')
  const [content,      setContent]      = useState(initial?.content      ?? '')
  const [mode,         setMode]         = useState<ResponseMode | ''>(initial?.response_mode ?? '')
  const [category,     setCategory]     = useState(initial?.category     ?? '')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim() || !content.trim()) return
    onSave({
      title:         title.trim(),
      content:       content.trim(),
      response_mode: (mode as ResponseMode) || null,
      category:      category.trim() || null,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2 p-3 bg-muted/40 rounded-lg border">
      <Input
        autoFocus
        placeholder="Prompt title"
        value={title}
        onChange={e => setTitle(e.target.value)}
        className="h-8 text-sm"
        maxLength={200}
      />
      <textarea
        placeholder="Prompt text…"
        value={content}
        onChange={e => setContent(e.target.value)}
        rows={3}
        className={cn(
          'w-full resize-none rounded-md border bg-background px-3 py-2 text-sm',
          'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
        )}
        maxLength={2000}
      />
      <div className="flex gap-2">
        <select
          value={mode}
          onChange={e => setMode(e.target.value as ResponseMode | '')}
          className={cn(
            'flex-1 h-8 rounded-md border bg-background px-2 text-xs',
            'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
          )}
        >
          {RESPONSE_MODES.map(m => (
            <option key={m.value} value={m.value}>{m.label} mode</option>
          ))}
        </select>
        <Input
          placeholder="Category (optional)"
          value={category}
          onChange={e => setCategory(e.target.value)}
          className="flex-1 h-8 text-xs"
          maxLength={100}
        />
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel} className="h-7 text-xs">
          <X className="w-3 h-3 mr-1" /> Cancel
        </Button>
        <Button
          type="submit"
          size="sm"
          className="h-7 text-xs"
          disabled={saving || !title.trim() || !content.trim()}
        >
          <Check className="w-3 h-3 mr-1" /> Save
        </Button>
      </div>
    </form>
  )
}

// ── Main panel ─────────────────────────────────────────────────────────────────

export function SavedPromptsPanel({ onUsePrompt, disabled }: SavedPromptsPanelProps) {
  const qc = useQueryClient()
  const [open,        setOpen]        = useState(false)
  const [showNew,     setShowNew]     = useState(false)
  const [editingId,   setEditingId]   = useState<string | null>(null)

  const { data: prompts = [] } = useQuery<SavedPrompt[]>({
    queryKey: ['saved-prompts'],
    queryFn:  savedPromptsApi.list,
    staleTime: 30_000,
  })

  const createMut = useMutation({
    mutationFn: savedPromptsApi.create,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['saved-prompts'] }); setShowNew(false) },
    onError:   () => toast.error('Could not save prompt.'),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<SavedPromptCreate & { is_pinned: boolean }> }) =>
      savedPromptsApi.update(id, payload),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['saved-prompts'] }); setEditingId(null) },
    onError:   () => toast.error('Could not update prompt.'),
  })

  const deleteMut = useMutation({
    mutationFn: savedPromptsApi.delete,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['saved-prompts'] }),
    onError:   () => toast.error('Could not delete prompt.'),
  })

  const useMut = useMutation({
    mutationFn: savedPromptsApi.recordUse,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['saved-prompts'] }),
  })

  const handleUse = useCallback((p: SavedPrompt) => {
    onUsePrompt(p.content)
    useMut.mutate(p.id)
  }, [onUsePrompt, useMut])

  const handlePin = useCallback((p: SavedPrompt) => {
    updateMut.mutate({ id: p.id, payload: { is_pinned: !p.is_pinned } })
  }, [updateMut])

  const pinnedPrompts   = prompts.filter(p =>  p.is_pinned)
  const unpinnedPrompts = prompts.filter(p => !p.is_pinned)

  return (
    <div className="relative">
      {/* Toggle button */}
      <button
        onClick={() => setOpen(v => !v)}
        disabled={disabled}
        title="Saved prompts"
        className={cn(
          'flex items-center gap-1.5 px-2.5 h-8 rounded-lg border text-xs font-medium',
          'transition-colors hover:bg-muted/50',
          open ? 'bg-primary/10 border-primary/30 text-primary' : 'bg-background text-muted-foreground',
          disabled && 'opacity-40 cursor-not-allowed',
        )}
      >
        {prompts.some(p => p.is_pinned) ? (
          <BookmarkCheck className="w-3.5 h-3.5" />
        ) : (
          <Bookmark className="w-3.5 h-3.5" />
        )}
        <span className="hidden sm:inline">Saved</span>
        {prompts.length > 0 && (
          <span className="ml-0.5 text-[10px] bg-muted rounded-full px-1.5">{prompts.length}</span>
        )}
        {open ? <ChevronDown className="w-3 h-3 ml-0.5" /> : <ChevronRight className="w-3 h-3 ml-0.5" />}
      </button>

      {/* Dropdown panel */}
      {open && (
        <div className={cn(
          'absolute bottom-full mb-2 right-0 z-50',
          'w-80 max-h-96 overflow-y-auto',
          'bg-popover border rounded-xl shadow-xl',
          'flex flex-col gap-0',
        )}>
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2 border-b sticky top-0 bg-popover z-10">
            <span className="text-sm font-semibold">Saved Prompts</span>
            <button
              onClick={() => { setShowNew(v => !v); setEditingId(null) }}
              className="flex items-center gap-1 text-xs text-primary hover:opacity-80 transition-opacity px-1.5 py-0.5 rounded-md hover:bg-primary/10"
            >
              <Plus className="w-3 h-3" /> New
            </button>
          </div>

          <div className="flex flex-col gap-1 p-2">
            {/* New prompt form */}
            {showNew && (
              <EditForm
                onSave={data => createMut.mutate(data)}
                onCancel={() => setShowNew(false)}
                saving={createMut.isPending}
              />
            )}

            {prompts.length === 0 && !showNew && (
              <p className="text-xs text-muted-foreground text-center py-6">
                No saved prompts yet.<br />
                Click <strong>New</strong> to save a reusable prompt.
              </p>
            )}

            {/* Pinned section */}
            {pinnedPrompts.length > 0 && (
              <>
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground px-1 pt-1 pb-0.5">Pinned</p>
                {pinnedPrompts.map(p => (
                  <PromptRow
                    key={p.id}
                    prompt={p}
                    isEditing={editingId === p.id}
                    onUse={() => handleUse(p)}
                    onPin={() => handlePin(p)}
                    onEdit={() => setEditingId(p.id)}
                    onSaveEdit={data => updateMut.mutate({ id: p.id, payload: data })}
                    onCancelEdit={() => setEditingId(null)}
                    onDelete={() => deleteMut.mutate(p.id)}
                    saving={updateMut.isPending}
                  />
                ))}
              </>
            )}

            {/* Unpinned section */}
            {unpinnedPrompts.length > 0 && (
              <>
                {pinnedPrompts.length > 0 && (
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground px-1 pt-2 pb-0.5">All Prompts</p>
                )}
                {unpinnedPrompts.map(p => (
                  <PromptRow
                    key={p.id}
                    prompt={p}
                    isEditing={editingId === p.id}
                    onUse={() => handleUse(p)}
                    onPin={() => handlePin(p)}
                    onEdit={() => setEditingId(p.id)}
                    onSaveEdit={data => updateMut.mutate({ id: p.id, payload: data })}
                    onCancelEdit={() => setEditingId(null)}
                    onDelete={() => deleteMut.mutate(p.id)}
                    saving={updateMut.isPending}
                  />
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Prompt row ─────────────────────────────────────────────────────────────────

interface PromptRowProps {
  prompt: SavedPrompt
  isEditing: boolean
  onUse: () => void
  onPin: () => void
  onEdit: () => void
  onSaveEdit: (data: SavedPromptCreate) => void
  onCancelEdit: () => void
  onDelete: () => void
  saving?: boolean
}

function PromptRow({
  prompt, isEditing, onUse, onPin, onEdit, onSaveEdit, onCancelEdit, onDelete, saving,
}: PromptRowProps) {
  if (isEditing) {
    return (
      <EditForm
        initial={prompt}
        onSave={onSaveEdit}
        onCancel={onCancelEdit}
        saving={saving}
      />
    )
  }

  return (
    <div className="group flex items-start gap-2 p-2 rounded-lg hover:bg-muted/40 transition-colors">
      <button
        onClick={onUse}
        className="flex-1 text-left min-w-0"
        title="Use this prompt"
      >
        <p className="text-sm font-medium truncate leading-snug">{prompt.title}</p>
        <p className="text-xs text-muted-foreground line-clamp-2 leading-snug mt-0.5">
          {prompt.content}
        </p>
        {(prompt.category || prompt.response_mode) && (
          <div className="flex gap-1 mt-1 flex-wrap">
            {prompt.category && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                {prompt.category}
              </span>
            )}
            {prompt.response_mode && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary">
                {prompt.response_mode}
              </span>
            )}
          </div>
        )}
      </button>

      {/* Action buttons — visible on hover */}
      <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-0.5">
        <button
          onClick={onPin}
          title={prompt.is_pinned ? 'Unpin' : 'Pin'}
          className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
        >
          {prompt.is_pinned
            ? <PinOff className="w-3 h-3" />
            : <Pin    className="w-3 h-3" />
          }
        </button>
        <button
          onClick={onEdit}
          title="Edit"
          className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
        >
          <Pencil className="w-3 h-3" />
        </button>
        <button
          onClick={onDelete}
          title="Delete"
          className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-destructive transition-colors"
        >
          <Trash2 className="w-3 h-3" />
        </button>
      </div>
    </div>
  )
}
