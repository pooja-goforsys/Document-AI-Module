import { useState, useEffect, useCallback } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'
import * as Dialog from '@radix-ui/react-dialog'
import {
  ChevronLeft, ChevronRight, X, ZoomIn, ZoomOut,
  ExternalLink, FileText, Minus, Plus,
} from 'lucide-react'
import { cn } from '@/lib/utils'

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

interface PDFViewerModalProps {
  open: boolean
  onClose: () => void
  fileUrl: string
  documentName: string
  initialPage?: number
  highlightText?: string | null
}

// Returns an HTML string with keyword matches wrapped in <mark>
function buildHighlightedStr(str: string, keywords: string[]): string {
  if (!keywords.length || !str) return escapeHtml(str)
  const pattern = keywords
    .map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|')
  try {
    const regex = new RegExp(`(${pattern})`, 'gi')
    // Build output: escape non-match parts, wrap matches
    const parts: string[] = []
    let last = 0
    str.replace(regex, (match, _, offset: number) => {
      parts.push(escapeHtml(str.slice(last, offset)))
      parts.push(`<mark style="background:rgba(255,214,0,0.55);border-radius:2px;padding:0 1px">${escapeHtml(match)}</mark>`)
      last = offset + match.length
      return match
    })
    parts.push(escapeHtml(str.slice(last)))
    return parts.join('')
  } catch {
    return escapeHtml(str)
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

export function PDFViewerModal({
  open,
  onClose,
  fileUrl,
  documentName,
  initialPage = 1,
  highlightText,
}: PDFViewerModalProps) {
  const [numPages, setNumPages]   = useState<number | null>(null)
  const [pageNumber, setPageNumber] = useState(initialPage)
  const [scale, setScale]         = useState(1.2)
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(false)

  useEffect(() => {
    if (open) {
      setPageNumber(initialPage)
      setLoading(true)
      setError(false)
    }
  }, [open, initialPage])

  const onDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages)
    setLoading(false)
  }

  const onDocumentLoadError = () => {
    setError(true)
    setLoading(false)
  }

  // Build keyword list from highlight_text (words > 4 chars, top 8)
  const keywords = highlightText
    ? highlightText.toLowerCase().split(/\s+/).filter(w => w.length > 4).slice(0, 8)
    : []

  const customTextRenderer = useCallback(
    ({ str }: { str: string }) => buildHighlightedStr(str, keywords),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [highlightText],
  )

  const goToPrev = () => setPageNumber(p => Math.max(1, p - 1))
  const goToNext = () => setPageNumber(p => Math.min(numPages ?? p, p + 1))
  const zoomIn   = () => setScale(s => Math.min(2.5, +(s + 0.2).toFixed(1)))
  const zoomOut  = () => setScale(s => Math.max(0.5, +(s - 0.2).toFixed(1)))
  const resetZoom = () => setScale(1.2)

  return (
    <Dialog.Root open={open} onOpenChange={v => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-50 backdrop-blur-sm" />
        <Dialog.Content
          className={cn(
            'fixed inset-4 z-50 flex flex-col',
            'bg-background rounded-xl shadow-2xl overflow-hidden border',
            'outline-none',
          )}
        >
          {/* ── Header ── */}
          <div className="flex items-center justify-between px-4 py-2.5 border-b bg-muted/30 shrink-0">
            <div className="flex items-center gap-2 min-w-0 flex-1">
              <FileText className="w-4 h-4 text-primary shrink-0" />
              <Dialog.Title className="text-sm font-medium truncate">{documentName}</Dialog.Title>
            </div>

            <div className="flex items-center gap-1 shrink-0 ml-2">
              {/* Page navigation */}
              {numPages != null && (
                <div className="flex items-center gap-1 mr-3">
                  <button
                    onClick={goToPrev}
                    disabled={pageNumber <= 1}
                    className="p-1 rounded hover:bg-muted disabled:opacity-40 transition-colors"
                    title="Previous page"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <span className="text-xs text-muted-foreground tabular-nums min-w-[6rem] text-center">
                    Page {pageNumber} of {numPages}
                  </span>
                  <button
                    onClick={goToNext}
                    disabled={pageNumber >= numPages}
                    className="p-1 rounded hover:bg-muted disabled:opacity-40 transition-colors"
                    title="Next page"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              )}

              {/* Zoom controls */}
              <button onClick={zoomOut} className="p-1.5 rounded hover:bg-muted transition-colors" title="Zoom out">
                <Minus className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={resetZoom}
                className="px-1.5 py-0.5 rounded hover:bg-muted text-xs tabular-nums min-w-[3rem] text-center transition-colors"
                title="Reset zoom"
              >
                {Math.round(scale * 100)}%
              </button>
              <button onClick={zoomIn} className="p-1.5 rounded hover:bg-muted transition-colors" title="Zoom in">
                <Plus className="w-3.5 h-3.5" />
              </button>

              <div className="w-px h-4 bg-border mx-1" />

              {/* Open in new tab */}
              <a
                href={fileUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="p-1.5 rounded hover:bg-muted transition-colors"
                title="Open in new tab"
              >
                <ExternalLink className="w-3.5 h-3.5" />
              </a>

              {/* Close */}
              <Dialog.Close asChild>
                <button className="p-1.5 rounded hover:bg-muted transition-colors ml-0.5" title="Close">
                  <X className="w-4 h-4" />
                </button>
              </Dialog.Close>
            </div>
          </div>

          {/* ── PDF content ── */}
          <div className="flex-1 overflow-auto flex justify-center bg-muted/10 py-4 px-2">
            {error ? (
              <div className="flex flex-col items-center justify-center gap-3 text-muted-foreground">
                <FileText className="w-10 h-10 opacity-30" />
                <p className="text-sm">Failed to load PDF.</p>
                <a
                  href={fileUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-primary underline underline-offset-2"
                >
                  Open in browser instead
                </a>
              </div>
            ) : (
              <Document
                file={fileUrl}
                onLoadSuccess={onDocumentLoadSuccess}
                onLoadError={onDocumentLoadError}
                loading={
                  <div className="flex items-center justify-center py-20 text-muted-foreground text-sm gap-2">
                    <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                    Loading PDF…
                  </div>
                }
              >
                {!loading && (
                  <Page
                    pageNumber={pageNumber}
                    scale={scale}
                    renderTextLayer
                    renderAnnotationLayer
                    customTextRenderer={keywords.length > 0 ? customTextRenderer : undefined}
                    className="shadow-lg"
                  />
                )}
              </Document>
            )}
          </div>

          {/* ── Highlight snippet footer ── */}
          {highlightText && (
            <div className="px-4 py-2 border-t bg-amber-50 dark:bg-amber-950/20 shrink-0">
              <p className="text-xs text-amber-800 dark:text-amber-300 leading-relaxed">
                <span className="font-semibold">Source excerpt: </span>
                <span className="italic">
                  &ldquo;{highlightText.length > 240 ? highlightText.slice(0, 240) + '…' : highlightText}&rdquo;
                </span>
              </p>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
