import { Link } from 'react-router-dom'
import { Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function EmptyDocumentsState() {
  return (
    <div className="flex flex-col items-center justify-center py-10 gap-4 text-center">
      <svg
        width="96" height="96" viewBox="0 0 96 96" fill="none"
        xmlns="http://www.w3.org/2000/svg" aria-hidden="true"
        className="opacity-80"
      >
        {/* folder base */}
        <rect x="8" y="28" width="80" height="56" rx="6"
          className="fill-muted stroke-border" strokeWidth="2" />
        {/* folder tab */}
        <path d="M8 28 C8 24 11 22 14 22 L36 22 C40 22 42 24 44 28"
          className="fill-muted stroke-border" strokeWidth="2" strokeLinejoin="round" />
        {/* document */}
        <rect x="30" y="18" width="36" height="46" rx="4"
          className="fill-background stroke-border" strokeWidth="2" />
        {/* document lines */}
        <line x1="38" y1="32" x2="58" y2="32" className="stroke-muted-foreground/40" strokeWidth="2" strokeLinecap="round" />
        <line x1="38" y1="40" x2="58" y2="40" className="stroke-muted-foreground/40" strokeWidth="2" strokeLinecap="round" />
        <line x1="38" y1="48" x2="50" y2="48" className="stroke-muted-foreground/40" strokeWidth="2" strokeLinecap="round" />
        {/* upload arrow */}
        <circle cx="72" cy="28" r="14" className="fill-primary/10 stroke-primary/30" strokeWidth="1.5" />
        <path d="M72 35 L72 21 M67 26 L72 21 L77 26"
          className="stroke-primary" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>

      <div>
        <p className="font-semibold text-sm">No documents uploaded yet</p>
        <p className="text-xs text-muted-foreground mt-1 max-w-[220px]">
          Upload your first document to start AI-powered search and chat.
        </p>
      </div>

      <Button size="sm" asChild>
        <Link to="/documents">
          <Upload className="w-3.5 h-3.5 mr-1.5" />
          Upload Document
        </Link>
      </Button>
    </div>
  )
}
