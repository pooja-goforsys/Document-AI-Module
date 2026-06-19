import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

interface CopyResponseButtonProps {
  content: string
  className?: string
}

export function CopyResponseButton({ content, className }: CopyResponseButtonProps) {
  const [copied, setCopied] = useState(false)

  async function handleCopy(e: React.MouseEvent) {
    e.stopPropagation()
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      toast.success('Response copied successfully')
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error('Failed to copy to clipboard.')
    }
  }

  return (
    <button
      onClick={handleCopy}
      title={copied ? 'Copied!' : 'Copy response'}
      className={cn(
        'p-1.5 rounded-md transition-all duration-150',
        'text-muted-foreground hover:text-foreground hover:bg-muted',
        copied && 'text-emerald-500 hover:text-emerald-500 hover:bg-emerald-50 dark:hover:bg-emerald-900/20',
        className,
      )}
    >
      {copied
        ? <Check  className="w-3.5 h-3.5" />
        : <Copy   className="w-3.5 h-3.5" />
      }
    </button>
  )
}
