import { useState } from 'react'
import { BookOpen, Loader2, X, Copy, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { summarizeDocument } from '@/services/api'
import { MarkdownRenderer } from './MarkdownRenderer'
import { cn } from '@/lib/utils'

type ScopeOption = 'full' | 'executive' | 'key_takeaways'

const SCOPE_LABELS: Record<ScopeOption, string> = {
  full:          'Full Summary',
  executive:     'Executive Summary',
  key_takeaways: 'Key Takeaways',
}

interface Props {
  docId: string
  docName: string
  onClose: () => void
}

export function SummarizeModal({ docId, docName, onClose }: Props) {
  const [scope, setScope]     = useState<ScopeOption>('full')
  const [loading, setLoading] = useState(false)
  const [summary, setSummary] = useState<string | null>(null)
  const [error, setError]     = useState<string | null>(null)
  const [copied, setCopied]   = useState(false)

  const run = async () => {
    setLoading(true)
    setError(null)
    setSummary(null)
    try {
      const res = await summarizeDocument(docId, scope)
      setSummary(res.summary)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Summarization failed.')
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = async () => {
    if (!summary) return
    try {
      await navigator.clipboard.writeText(summary)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* clipboard unavailable */ }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      <div className="relative w-full max-w-xl bg-background rounded-2xl border shadow-2xl flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-center gap-2 px-5 py-4 border-b shrink-0">
          <BookOpen className="w-4 h-4 text-primary" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold">Document Summary</p>
            <p className="text-xs text-muted-foreground truncate">{docName}</p>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scope selector */}
        <div className="px-5 py-3 border-b shrink-0">
          <div className="flex gap-2">
            {(Object.keys(SCOPE_LABELS) as ScopeOption[]).map(s => (
              <button
                key={s}
                onClick={() => setScope(s)}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border',
                  scope === s
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'bg-background text-muted-foreground border-border hover:bg-muted/50',
                )}
              >
                {SCOPE_LABELS[s]}
              </button>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4 min-h-0">
          {!summary && !loading && !error && (
            <div className="flex flex-col items-center justify-center h-32 gap-3 text-center">
              <BookOpen className="w-8 h-8 text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">
                Select a scope and click Generate to create an AI summary.
              </p>
            </div>
          )}

          {loading && (
            <div className="flex flex-col items-center justify-center h-32 gap-3">
              <Loader2 className="w-6 h-6 animate-spin text-primary" />
              <p className="text-sm text-muted-foreground">Generating summary…</p>
            </div>
          )}

          {error && (
            <div className="rounded-lg bg-destructive/10 border border-destructive/30 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          )}

          {summary && (
            <div className="ai-response">
              <MarkdownRenderer content={summary} />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-2 px-5 py-3 border-t shrink-0">
          {summary && (
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
          )}
          <div className="flex-1" />
          <Button variant="outline" size="sm" onClick={onClose}>
            Close
          </Button>
          <Button size="sm" onClick={run} disabled={loading}>
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> : null}
            Generate
          </Button>
        </div>
      </div>
    </div>
  )
}
