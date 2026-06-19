import { Link } from 'react-router-dom'
import { MessageSquare } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function EmptyChatsState() {
  return (
    <div className="flex flex-col items-center justify-center py-10 gap-4 text-center">
      <svg
        width="88" height="88" viewBox="0 0 88 88" fill="none"
        xmlns="http://www.w3.org/2000/svg" aria-hidden="true"
        className="opacity-80"
      >
        {/* main bubble */}
        <rect x="8" y="12" width="56" height="44" rx="10"
          className="fill-primary/10 stroke-primary/30" strokeWidth="2" />
        {/* bubble tail */}
        <path d="M18 56 L12 68 L28 60"
          className="fill-primary/10 stroke-primary/30" strokeWidth="2"
          strokeLinejoin="round" strokeLinecap="round" />
        {/* text lines */}
        <line x1="20" y1="28" x2="48" y2="28" className="stroke-primary/50" strokeWidth="2" strokeLinecap="round" />
        <line x1="20" y1="36" x2="44" y2="36" className="stroke-primary/50" strokeWidth="2" strokeLinecap="round" />
        <line x1="20" y1="44" x2="38" y2="44" className="stroke-primary/50" strokeWidth="2" strokeLinecap="round" />
        {/* secondary bubble */}
        <rect x="36" y="44" width="44" height="32" rx="8"
          className="fill-muted stroke-border" strokeWidth="2" />
        {/* secondary tail */}
        <path d="M72 76 L78 86 L64 78"
          className="fill-muted stroke-border" strokeWidth="2"
          strokeLinejoin="round" strokeLinecap="round" />
        {/* secondary lines */}
        <line x1="46" y1="56" x2="70" y2="56" className="stroke-muted-foreground/40" strokeWidth="2" strokeLinecap="round" />
        <line x1="46" y1="64" x2="64" y2="64" className="stroke-muted-foreground/40" strokeWidth="2" strokeLinecap="round" />
      </svg>

      <div>
        <p className="font-semibold text-sm">No conversations yet</p>
        <p className="text-xs text-muted-foreground mt-1 max-w-[200px]">
          Ask a question about your documents to begin chatting.
        </p>
      </div>

      <Button size="sm" asChild>
        <Link to="/chat">
          <MessageSquare className="w-3.5 h-3.5 mr-1.5" />
          Start Chatting
        </Link>
      </Button>
    </div>
  )
}
