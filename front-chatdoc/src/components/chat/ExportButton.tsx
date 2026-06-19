import { useState } from 'react'
import { Download, FileText, Copy, Check } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  content: string
  filename?: string
  className?: string
}

export function ExportButton({ content, filename = 'response', className }: Props) {
  const [open, setOpen]       = useState(false)
  const [copied, setCopied]   = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
      setOpen(false)
    } catch { /* clipboard unavailable */ }
  }

  const handleDownload = () => {
    const blob = new Blob([content], { type: 'text/markdown; charset=utf-8' })
    const url  = URL.createObjectURL(blob)
    const a    = Object.assign(document.createElement('a'), {
      href: url,
      download: `${filename}.md`,
    })
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    setOpen(false)
  }

  return (
    <div className={cn('relative', className)}>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1 text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors px-1 py-0.5 rounded hover:bg-muted/50"
        title="Export"
      >
        <Download className="w-3 h-3" />
        <span>Export</span>
      </button>

      {open && (
        <>
          {/* backdrop */}
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute bottom-full mb-1 left-0 z-20 min-w-[140px] rounded-lg border bg-popover shadow-md py-1 text-xs">
            <button
              onClick={handleCopy}
              className="flex w-full items-center gap-2 px-3 py-1.5 hover:bg-muted/60 transition-colors"
            >
              {copied
                ? <Check className="w-3.5 h-3.5 text-green-500" />
                : <Copy className="w-3.5 h-3.5 text-muted-foreground" />
              }
              {copied ? 'Copied!' : 'Copy text'}
            </button>
            <button
              onClick={handleDownload}
              className="flex w-full items-center gap-2 px-3 py-1.5 hover:bg-muted/60 transition-colors"
            >
              <FileText className="w-3.5 h-3.5 text-muted-foreground" />
              Download .md
            </button>
          </div>
        </>
      )}
    </div>
  )
}
