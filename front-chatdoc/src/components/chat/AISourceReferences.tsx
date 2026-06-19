import { useState } from 'react'
import { FileText, ExternalLink, BookOpen, BookMarked } from 'lucide-react'
import { getDocumentFileUrl } from '@/services/api'
import { PDFViewerModal } from './PDFViewerModal'
import type { SourceCitation } from '@/types'
import { cn } from '@/lib/utils'

interface Props {
  sources: SourceCitation[]
  className?: string
}

interface ViewerState {
  fileUrl: string
  docName: string
  page: number
  highlightText: string | null
}

export function AISourceReferences({ sources, className }: Props) {
  const [viewer, setViewer] = useState<ViewerState | null>(null)

  if (!sources?.length) return null

  // Deduplicate by document_id; collect all cited pages with their chunk data
  const byDoc = new Map<string, {
    id: string
    name: string
    pages: Map<number, { chunkId: string | null; highlight: string | null }>
    score: number
    domain: string | null
  }>()

  for (const s of sources) {
    if (!byDoc.has(s.document_id)) {
      byDoc.set(s.document_id, {
        id:     s.document_id,
        name:   s.document_name,
        pages:  new Map(),
        score:  s.score,
        domain: s.domain_name ?? null,
      })
    }
    const entry = byDoc.get(s.document_id)!
    if (s.page_number != null && !entry.pages.has(s.page_number)) {
      entry.pages.set(s.page_number, {
        chunkId:   s.chunk_id ?? null,
        highlight: s.highlight_text ?? null,
      })
    }
    entry.score = Math.max(entry.score, s.score)
  }

  const docs = [...byDoc.values()].sort((a, b) => b.score - a.score)

  // Detect whether all sources share a single domain
  const domains = [...new Set(docs.map(d => d.domain).filter(Boolean))]
  const sharedDomain = domains.length === 1 ? domains[0] : null

  return (
    <>
      <div className={cn('mt-3 pt-3 border-t border-border/60', className)}>

        {/* Domain summary header */}
        {sharedDomain ? (
          <div className="flex items-center gap-1.5 mb-2">
            <BookOpen className="w-3 h-3 text-emerald-500 shrink-0" />
            <p className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">
              {docs.length} {sharedDomain} document{docs.length !== 1 ? 's' : ''} analyzed
            </p>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 mb-2">
            <BookMarked className="w-3 h-3 text-muted-foreground/70 shrink-0" />
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Sources
            </p>
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          {docs.map(doc => {
            const sortedPages = [...doc.pages.keys()].sort((a, b) => a - b)
            const pct         = Math.round(doc.score * 100)
            const fileUrl     = getDocumentFileUrl(doc.id)

            return (
              <div
                key={doc.id}
                className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2"
              >
                {/* Document name row */}
                <div className="flex items-start gap-2">
                  <FileText className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary/60" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-[12px] font-medium text-foreground/90 truncate max-w-[200px]">
                        {doc.name}
                      </span>
                      <span className="text-[10px] text-muted-foreground/70 shrink-0">
                        {pct}% match
                      </span>
                    </div>
                    {!sharedDomain && doc.domain && (
                      <p className="text-[10px] text-emerald-600 dark:text-emerald-400 mt-0.5 font-medium">
                        {doc.domain}
                      </p>
                    )}
                  </div>

                  {/* Open in new tab */}
                  <a
                    href={fileUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="shrink-0 text-muted-foreground/40 hover:text-primary transition-colors"
                    title="Open document in new tab"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                </div>

                {/* Page citation buttons */}
                {sortedPages.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5 ml-5">
                    {sortedPages.map(page => {
                      const data = doc.pages.get(page)!
                      return (
                        <button
                          key={page}
                          onClick={() => setViewer({
                            fileUrl,
                            docName:       doc.name,
                            page,
                            highlightText: data.highlight,
                          })}
                          className={cn(
                            'inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded',
                            'text-[10px] font-medium',
                            'border border-primary/30 bg-primary/5 text-primary/80',
                            'hover:bg-primary/15 hover:border-primary/50 hover:text-primary',
                            'transition-colors cursor-pointer',
                          )}
                          title={data.highlight ? `Page ${page} — click to view highlighted excerpt` : `Go to page ${page}`}
                        >
                          p.{page}
                          <ExternalLink className="w-2.5 h-2.5 opacity-60" />
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* PDF viewer modal */}
      {viewer && (
        <PDFViewerModal
          open
          onClose={() => setViewer(null)}
          fileUrl={viewer.fileUrl}
          documentName={viewer.docName}
          initialPage={viewer.page}
          highlightText={viewer.highlightText}
        />
      )}
    </>
  )
}
