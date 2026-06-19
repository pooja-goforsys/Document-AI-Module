import { useEffect, useId, useState } from 'react'
import mermaid from 'mermaid'
import { AlertTriangle } from 'lucide-react'

let _initialized = false
function ensureInit() {
  if (_initialized) return
  mermaid.initialize({
    startOnLoad: false,
    theme: 'neutral',
    securityLevel: 'loose',
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, sans-serif',
    fontSize: 13,
    flowchart: { curve: 'basis', padding: 16 },
  })
  _initialized = true
}

interface Props {
  code: string
}

export function AIMermaidDiagram({ code }: Props) {
  const uid = useId().replace(/:/g, '')
  const id = `mermaid-${uid}`
  const [svg, setSvg]     = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    ensureInit()
    setSvg('')
    setError(null)

    mermaid.render(id, code)
      .then(result => setSvg(result.svg))
      .catch(err => {
        const msg = err instanceof Error ? err.message : String(err)
        setError(msg)
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code])

  if (error) {
    return (
      <div className="my-3 flex items-start gap-2 rounded-lg border border-amber-300/50 bg-amber-50 dark:bg-amber-900/20 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
        <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        <span>Diagram render error: {error}</span>
      </div>
    )
  }

  if (!svg) {
    return (
      <div className="my-3 h-40 rounded-xl border bg-muted/20 animate-pulse" />
    )
  }

  return (
    <div
      className="my-3 overflow-x-auto rounded-xl border bg-white dark:bg-zinc-900 p-4 text-center"
      // mermaid outputs safe SVG; it has already been sanitized
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
