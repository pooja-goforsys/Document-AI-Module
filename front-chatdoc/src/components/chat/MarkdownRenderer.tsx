import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { AIMermaidDiagram } from './AIMermaidDiagram'
// Register only the languages a document assistant realistically needs
import python     from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript'
import c          from 'react-syntax-highlighter/dist/esm/languages/prism/c'
import cpp        from 'react-syntax-highlighter/dist/esm/languages/prism/cpp'
import java       from 'react-syntax-highlighter/dist/esm/languages/prism/java'
import sql        from 'react-syntax-highlighter/dist/esm/languages/prism/sql'
import bash       from 'react-syntax-highlighter/dist/esm/languages/prism/bash'
import json       from 'react-syntax-highlighter/dist/esm/languages/prism/json'
import markup     from 'react-syntax-highlighter/dist/esm/languages/prism/markup'
import css        from 'react-syntax-highlighter/dist/esm/languages/prism/css'
import { Check, Copy } from 'lucide-react'
import { cn } from '@/lib/utils'

SyntaxHighlighter.registerLanguage('python',     python)
SyntaxHighlighter.registerLanguage('javascript', javascript)
SyntaxHighlighter.registerLanguage('js',         javascript)
SyntaxHighlighter.registerLanguage('typescript', typescript)
SyntaxHighlighter.registerLanguage('ts',         typescript)
SyntaxHighlighter.registerLanguage('c',          c)
SyntaxHighlighter.registerLanguage('cpp',        cpp)
SyntaxHighlighter.registerLanguage('java',       java)
SyntaxHighlighter.registerLanguage('sql',        sql)
SyntaxHighlighter.registerLanguage('bash',       bash)
SyntaxHighlighter.registerLanguage('sh',         bash)
SyntaxHighlighter.registerLanguage('json',       json)
SyntaxHighlighter.registerLanguage('html',       markup)
SyntaxHighlighter.registerLanguage('xml',        markup)
SyntaxHighlighter.registerLanguage('css',        css)

function CopyCodeButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard not available
    }
  }

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 text-xs text-zinc-400 hover:text-zinc-200 transition-colors"
    >
      {copied
        ? <Check className="w-3 h-3" />
        : <Copy className="w-3 h-3" />
      }
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

const components: Components = {
  // Remove the default <pre> wrapper — SyntaxHighlighter renders its own container
  pre({ children }) {
    return <>{children}</>
  },

  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '')

    if (!match) {
      return (
        <code
          className="bg-muted/70 px-1.5 py-0.5 rounded text-[11px] font-mono text-foreground/90"
          {...props}
        >
          {children}
        </code>
      )
    }

    const language = match[1]
    const code = String(children).replace(/\n$/, '')

    // Render mermaid blocks as interactive diagrams
    if (language === 'mermaid') {
      return <AIMermaidDiagram code={code} />
    }

    return (
      <div className="relative mb-3 rounded-md overflow-hidden border border-zinc-700/50">
        <div className="flex items-center justify-between bg-zinc-800 dark:bg-zinc-900 px-3 py-1.5">
          <span className="text-[11px] text-zinc-400 font-mono">{language}</span>
          <CopyCodeButton code={code} />
        </div>
        <SyntaxHighlighter
          language={language}
          style={oneDark}
          PreTag="div"
          customStyle={{ margin: 0, borderRadius: 0, fontSize: '12px', padding: '12px 16px' }}
          codeTagProps={{ style: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: '12px' } }}
        >
          {code}
        </SyntaxHighlighter>
      </div>
    )
  },

  table({ children }) {
    return (
      <div className="overflow-x-auto mb-3 rounded-md border border-border">
        <table className="w-full border-collapse text-xs">
          {children}
        </table>
      </div>
    )
  },

  thead({ children }) {
    return <thead className="bg-muted/60 border-b border-border">{children}</thead>
  },

  th({ children }) {
    return (
      <th className="px-3 py-2 text-left font-semibold text-xs border-r border-border last:border-r-0">
        {children}
      </th>
    )
  },

  td({ children }) {
    return (
      <td className="px-3 py-2 text-xs border-r border-border last:border-r-0">
        {children}
      </td>
    )
  },

  tr({ children, ...props }) {
    return (
      <tr className="border-b border-border last:border-b-0 even:bg-muted/20" {...props}>
        {children}
      </tr>
    )
  },

  h1({ children }) {
    return (
      <h1 className="text-[15px] font-bold mt-4 mb-2 first:mt-0 text-foreground">
        {children}
      </h1>
    )
  },

  h2({ children }) {
    return (
      <h2 className="text-[13px] font-semibold mt-3 mb-1.5 text-foreground/90">
        {children}
      </h2>
    )
  },

  h3({ children }) {
    return (
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mt-2.5 mb-1">
        {children}
      </h3>
    )
  },

  p({ children }) {
    return <p className="text-[13px] leading-relaxed mb-2 last:mb-0">{children}</p>
  },

  ul({ children }) {
    return <ul className="list-disc list-outside pl-4 mb-2 space-y-0.5">{children}</ul>
  },

  ol({ children }) {
    return <ol className="list-decimal list-outside pl-4 mb-2 space-y-0.5">{children}</ol>
  },

  li({ children }) {
    return <li className="text-[13px] leading-relaxed">{children}</li>
  },

  strong({ children }) {
    return <strong className="font-semibold text-foreground">{children}</strong>
  },

  em({ children }) {
    return <em className="italic">{children}</em>
  },

  hr() {
    return <hr className="border-border my-3" />
  },

  blockquote({ children }) {
    return (
      <blockquote className="border-l-2 border-primary/40 pl-3 italic text-muted-foreground my-2 text-[13px]">
        {children}
      </blockquote>
    )
  },

  a({ href, children }) {
    return (
      <a
        href={href}
        className="text-primary underline underline-offset-2 hover:opacity-80"
        target="_blank"
        rel="noopener noreferrer"
      >
        {children}
      </a>
    )
  },
}

interface MarkdownRendererProps {
  content: string
  className?: string
}

export function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  return (
    <div className={cn('min-w-0', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
