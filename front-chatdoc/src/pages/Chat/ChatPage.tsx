import { useState, useRef, useEffect, useCallback } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Bot, User, Sparkles, Send, RefreshCw, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  streamChatQuery,
  streamRegenerateResponse,
  getSessionMessages,
  getSession,
  updateSession,
  submitFeedback,
} from '@/services/api'
import { cn, formatRelativeTime } from '@/lib/utils'
import type {
  ChatMessage,
  ChatScope,
  ChatSession,
  SourceCitation,
  ResponseMode,
  FeedbackRating,
  StatusStep,
} from '@/types'
import { ChatSidebar }          from '@/components/chat/ChatSidebar'
import { CopyResponseButton }   from '@/components/chat/CopyResponseButton'
import { MarkdownRenderer }     from '@/components/chat/MarkdownRenderer'
import { ContextSelector }      from '@/components/chat/ContextSelector'
import { RelatedQuestions }     from '@/components/chat/RelatedQuestions'
import { ConfidenceBadge }      from '@/components/chat/ConfidenceBadge'
import { StatusIndicator }      from '@/components/chat/StatusIndicator'
import { FeedbackButtons }      from '@/components/chat/FeedbackButtons'
import { ResponseModeSelector } from '@/components/chat/ResponseModeSelector'
import { AIChartResponse }      from '@/components/chat/AIChartResponse'
import { AITimelineResponse }   from '@/components/chat/AITimelineResponse'
import { AISourceReferences }   from '@/components/chat/AISourceReferences'
import { ExportButton }         from '@/components/chat/ExportButton'
import { ResponseTypeBadge }    from '@/components/chat/ResponseTypeBadge'
import { DomainSelector }       from '@/components/chat/DomainSelector'
import { SavedPromptsPanel }    from '@/components/chat/SavedPromptsPanel'
import { extractRelatedQuestions } from '@/lib/parseResponse'
import type { AIResponseMetadata } from '@/types'

// ── Helpers ────────────────────────────────────────────────────────────────────

function levelFromScore(score: number): string {
  if (score >= 80) return 'high'
  if (score >= 60) return 'good'
  if (score >= 40) return 'moderate'
  return 'low'
}

// ── Suggested prompts ─────────────────────────────────────────────────────────

const PROMPTS_ALL = [
  'Summarize the key points from the uploaded documents',
  'What are the main topics covered in the documents?',
  'List the important information from the files',
  'What actions or steps are described in the documents?',
]
const PROMPTS_FOLDER = [
  'Summarize the documents in this folder',
  'What topics are covered in this folder?',
  'List the key points from these documents',
  'What are the main findings in this folder?',
]
const PROMPTS_DOCUMENT = [
  'Summarize this document',
  'What are the key points of this document?',
  'Explain the main concepts in this document',
  'What conclusions does this document reach?',
]

function getSuggestedPrompts(scope: ChatScope): string[] {
  if (scope.type === 'folder')   return PROMPTS_FOLDER
  if (scope.type === 'document') return PROMPTS_DOCUMENT
  return PROMPTS_ALL
}

// ── Session factory ───────────────────────────────────────────────────────────

const DEFAULT_SCOPE: ChatScope = { type: 'all', id: null, name: null }

function newSession(scope: ChatScope = DEFAULT_SCOPE): ChatSession {
  return {
    id:         Date.now().toString(),
    backendId:  null,
    title:      'New Chat',
    messages:   [],
    scope,
    pinned:     false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex gap-3 message-enter">
      <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
        <Bot className="w-4 h-4 text-primary" />
      </div>
      <div className="bg-card border rounded-2xl rounded-tl-sm px-4 py-3">
        <div className="flex gap-1 items-center h-4">
          <div className="typing-dot w-1.5 h-1.5 bg-muted-foreground/60 rounded-full" />
          <div className="typing-dot w-1.5 h-1.5 bg-muted-foreground/60 rounded-full" />
          <div className="typing-dot w-1.5 h-1.5 bg-muted-foreground/60 rounded-full" />
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const queryClient = useQueryClient()
  const location    = useLocation()
  const navigate    = useNavigate()

  const initial = newSession()
  const [sessions, setSessions]         = useState<ChatSession[]>([initial])
  const [activeId, setActiveId]         = useState<string>(initial.id)
  const [input, setInput]               = useState('')
  const [isStreaming, setIsStreaming]   = useState(false)
  const [responseMode, setResponseMode] = useState<ResponseMode>('auto')

  // Capture the session ID from React Router navigation state ONCE at mount time.
  // Using a ref (not reactive state) means subsequent re-renders caused by
  // navigate/location changes do NOT reset or re-read this value.
  const pendingSessionIdRef = useRef<string | null>(
    (location.state as { sessionId?: string } | null)?.sessionId ?? null,
  )
  // fetchedRef ensures Strict Mode's double-invocation of effects never fires
  // two parallel fetches for the same session.
  const fetchedRef = useRef(false)

  // True while we are loading an existing session from a dashboard click.
  // Prevents the blank "new chat" empty state from flashing before data arrives.
  const [sessionLoading, setSessionLoading] = useState(() => !!pendingSessionIdRef.current)

  const bottomRef   = useRef<HTMLDivElement>(null)
  const inputRef    = useRef<HTMLInputElement>(null)
  // Mirrors `sessions` so the restore effect can read current sessions without
  // capturing a stale closure (sessions is excluded from effect deps on purpose).
  const sessionsRef = useRef(sessions)
  useEffect(() => { sessionsRef.current = sessions }, [sessions])

  const activeSession = sessions.find(s => s.id === activeId) ?? sessions[0]

  // ── Restore session from navigation state (one-shot on mount) ──────────────
  useEffect(() => {
    const backendId = pendingSessionIdRef.current
    if (!backendId || fetchedRef.current) return
    fetchedRef.current = true

    // Clear navigation state so pressing Back and then Forward doesn't
    // re-trigger a duplicate load after the component remounts.
    navigate('/chat', { replace: true, state: null })

    // If the session is already in local state (e.g. user navigated back/fwd),
    // just make it active — no network call needed.
    const existing = sessionsRef.current.find(s => s.backendId === backendId)
    if (existing) {
      setActiveId(existing.id)
      setSessionLoading(false)
      return
    }

    // Fetch session metadata + messages from the backend.
    Promise.all([
      getSession(backendId),
      getSessionMessages(backendId),
    ]).then(([sessionMeta, msgs]) => {
      const localId  = Date.now().toString()
      const messages: ChatMessage[] = msgs.map(m => ({
        id:              m.id,
        content:         m.content,
        role:            m.role,
        timestamp:       m.created_at,
        sources:         m.sources ?? [],
        confidence:      m.confidence_score ?? null,
        confidenceLevel: m.confidence_score != null ? levelFromScore(m.confidence_score) : null,
        responseMode:    m.response_mode ?? null,
        metadata:        null,
      }))
      const scope: ChatScope = {
        type: (sessionMeta.scope_type as ChatScope['type']) ?? 'all',
        id:   sessionMeta.scope_id,
        name: sessionMeta.scope_name,
      }
      const restored: ChatSession = {
        id:         localId,
        backendId,
        title:      sessionMeta.title,
        messages,
        scope,
        pinned:     sessionMeta.pinned ?? false,
        created_at: msgs[0]?.created_at ?? new Date().toISOString(),
        updated_at: msgs.at(-1)?.created_at ?? new Date().toISOString(),
      }
      // Guard: skip if a concurrent path already added this session.
      setSessions(p => p.find(s => s.backendId === backendId) ? p : [restored, ...p])
      setActiveId(localId)
      setSessionLoading(false)
    }).catch(() => {
      toast.error('Could not load the selected chat session.')
      setSessionLoading(false)
    })
  // Empty deps: this must run exactly once on mount. pendingSessionIdRef and
  // fetchedRef are stable refs — they are not reactive and must not be listed.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [activeSession.messages, isStreaming])

  // Scope is locked once the session has a backendId
  const scopeLocked = activeSession.backendId !== null

  function updateScope(scope: ChatScope) {
    if (scopeLocked) return
    setSessions(prev => prev.map(s => s.id === activeId ? { ...s, scope } : s))
  }

  // ── Send message ──────────────────────────────────────────────────────────
  const sendMessage = useCallback(async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || isStreaming) return

    setInput('')
    setIsStreaming(true)

    const userMsgId = Date.now().toString()
    const userMsg: ChatMessage = {
      id:        userMsgId,
      content:   trimmed,
      role:      'user',
      timestamp: new Date().toISOString(),
    }

    setSessions(prev => prev.map(s => {
      if (s.id !== activeId) return s
      const msgs  = [...s.messages, userMsg]
      const title = msgs.length === 1
        ? trimmed.slice(0, 40) + (trimmed.length > 40 ? '…' : '')
        : s.title
      return { ...s, messages: msgs, title, updated_at: new Date().toISOString() }
    }))

    const aiMsgId = (Date.now() + 1).toString()
    setSessions(prev => prev.map(s =>
      s.id === activeId
        ? { ...s, messages: [...s.messages, {
            id: aiMsgId, content: '', role: 'assistant',
            timestamp: new Date().toISOString(), isStreaming: true,
            statusStep: null,
          }] }
        : s,
    ))

    const currentSession  = sessions.find(s => s.id === activeId)
    const currentBackendId = currentSession?.backendId ?? null
    const currentScope     = currentSession?.scope ?? DEFAULT_SCOPE

    console.log('[Chat] ── SEND REQUEST ──────────────────────────────────')
    console.log('[Chat] Question   :', trimmed)
    console.log('[Chat] Session ID :', currentBackendId)
    console.log('[Chat] Scope      :', JSON.stringify(currentScope))
    console.log('[Chat] Mode       :', responseMode)

    try {
      let fullText = ''
      let sources: SourceCitation[] = []
      let newBackendSessionId: string | null = null
      let returnedScope: ChatScope | null = null
      let aiMetadata: AIResponseMetadata | null = null
      let gotClarification = false

      for await (const evt of streamChatQuery(trimmed, currentBackendId, currentScope, responseMode)) {
        if (evt.event === 'clarification') {
          gotClarification = true
          setSessions(prev => prev.map(s => {
            if (s.id !== activeId) return s
            return {
              ...s,
              messages: s.messages.map(m =>
                m.id === aiMsgId
                  ? {
                      ...m,
                      isStreaming:       false,
                      statusStep:        null,
                      requiresSelection: true,
                      selectionDomains:  evt.data.domains,
                      selectionQuestion: trimmed,
                    }
                  : m
              ),
            }
          }))
          break
        } else if (evt.event === 'status') {
          setSessions(prev => prev.map(s => {
            if (s.id !== activeId) return s
            return {
              ...s,
              messages: s.messages.map(m =>
                m.id === aiMsgId
                  ? { ...m, statusStep: evt.data.step as StatusStep, statusLabel: evt.data.label }
                  : m
              ),
            }
          }))
        } else if (evt.event === 'token') {
          if (!fullText) console.log('[Chat] First token received — streaming started')
          fullText += evt.data.text
          setSessions(prev => prev.map(s => {
            if (s.id !== activeId) return s
            return {
              ...s,
              messages: s.messages.map(m =>
                m.id === aiMsgId
                  ? { ...m, content: fullText, statusStep: null }
                  : m
              ),
            }
          }))
        } else if (evt.event === 'sources') {
          sources = evt.data.sources ?? []
          if (evt.data.session_id) newBackendSessionId = evt.data.session_id
          console.log('[Chat] Sources received:', sources.length, 'citation(s)')
        } else if (evt.event === 'metadata') {
          aiMetadata = evt.data as AIResponseMetadata
        } else if (evt.event === 'provider_warning') {
          console.warn('[Chat] Provider warning:', evt.data.message)
        } else if (evt.event === 'not_found') {
          console.warn('[Chat] Retrieval gate blocked response:', evt.data)
        } else if (evt.event === 'done') {
          if (evt.data.session_id) newBackendSessionId = evt.data.session_id
          if (evt.data.scope_type) {
            returnedScope = {
              type: evt.data.scope_type as ChatScope['type'],
              id:   evt.data.scope_id ?? null,
              name: evt.data.scope_name ?? null,
            }
          }
          console.log('[Chat] Done event — session:', newBackendSessionId)
        } else if (evt.event === 'confidence') {
          setSessions(prev => prev.map(s => {
            if (s.id !== activeId) return s
            return {
              ...s,
              messages: s.messages.map(m =>
                m.id === aiMsgId
                  ? { ...m, confidence: evt.data.score, confidenceLevel: evt.data.level }
                  : m
              ),
            }
          }))
        } else if (evt.event === 'error') {
          const errMsg = evt.data.message ?? 'Something went wrong.'
          console.error('[Chat] Error SSE event:', errMsg)
          console.error('Streaming error:', evt.data)
          fullText = `*${errMsg}*`
          toast.error(errMsg)
          break
        }
      }

      console.log(`[Chat] Stream complete — ${fullText.length} chars, ${sources.length} source(s), session=${newBackendSessionId}`)

      if (!gotClarification) {
        setSessions(prev => prev.map(s => {
          if (s.id !== activeId) return s
          return {
            ...s,
            backendId: newBackendSessionId ?? s.backendId,
            scope:     returnedScope ?? s.scope,
            messages:  s.messages.map(m =>
              m.id === aiMsgId
                ? { ...m, content: fullText, sources, isStreaming: false, statusStep: null, responseMode, metadata: aiMetadata }
                : m,
            ),
          }
        }))
        queryClient.invalidateQueries({ queryKey: ['queries'] })
        queryClient.invalidateQueries({ queryKey: ['stats']   })
      }

    } catch (err) {
      setSessions(prev => prev.map(s =>
        s.id === activeId
          ? { ...s, messages: s.messages.filter(m => m.id !== aiMsgId) }
          : s,
      ))
      if (err instanceof Error && err.message === 'SESSION_EXPIRED') {
        toast.error('Your session has expired. Please sign in again.')
      } else {
        toast.error('Failed to get a response. Please try again.')
      }
      console.error('Streaming error:', err)
      console.error('SSE stream error:', err)
    } finally {
      setIsStreaming(false)
    }
  }, [activeId, isStreaming, sessions, queryClient, responseMode])

  // ── Regenerate last response ──────────────────────────────────────────────
  const regenerate = useCallback(async () => {
    const currentSession = sessions.find(s => s.id === activeId)
    if (!currentSession?.backendId || isStreaming) return

    const lastAiMsg = [...currentSession.messages].reverse().find(m => m.role === 'assistant')
    if (!lastAiMsg) return

    setIsStreaming(true)

    // Remove last AI message locally
    const newAiMsgId = (Date.now() + 1).toString()
    setSessions(prev => prev.map(s => {
      if (s.id !== activeId) return s
      const filtered = s.messages.filter(m => m.id !== lastAiMsg.id)
      return {
        ...s,
        messages: [
          ...filtered,
          { id: newAiMsgId, content: '', role: 'assistant' as const, timestamp: new Date().toISOString(), isStreaming: true, statusStep: null },
        ],
      }
    }))

    try {
      let fullText = ''
      let sources: SourceCitation[] = []
      let aiMetadata: AIResponseMetadata | null = null

      for await (const evt of streamRegenerateResponse(currentSession.backendId)) {
        if (evt.event === 'status') {
          setSessions(prev => prev.map(s => {
            if (s.id !== activeId) return s
            return {
              ...s,
              messages: s.messages.map(m =>
                m.id === newAiMsgId
                  ? { ...m, statusStep: evt.data.step as StatusStep, statusLabel: evt.data.label }
                  : m
              ),
            }
          }))
        } else if (evt.event === 'token') {
          fullText += evt.data.text
          setSessions(prev => prev.map(s => {
            if (s.id !== activeId) return s
            return {
              ...s,
              messages: s.messages.map(m =>
                m.id === newAiMsgId ? { ...m, content: fullText, statusStep: null } : m,
              ),
            }
          }))
        } else if (evt.event === 'sources') {
          sources = evt.data.sources ?? []
        } else if (evt.event === 'metadata') {
          aiMetadata = evt.data as AIResponseMetadata
        } else if (evt.event === 'provider_warning') {
          console.warn('[Chat] Provider warning:', evt.data.message)
        } else if (evt.event === 'not_found') {
          console.warn('[Chat] Retrieval gate blocked response:', evt.data)
        } else if (evt.event === 'confidence') {
          setSessions(prev => prev.map(s => {
            if (s.id !== activeId) return s
            return {
              ...s,
              messages: s.messages.map(m =>
                m.id === newAiMsgId
                  ? { ...m, confidence: evt.data.score, confidenceLevel: evt.data.level }
                  : m
              ),
            }
          }))
        } else if (evt.event === 'error') {
          console.error('Streaming error:', evt.data)
          toast.error(evt.data.message ?? 'Regeneration failed.')
          break
        }
      }

      setSessions(prev => prev.map(s => {
        if (s.id !== activeId) return s
        return {
          ...s,
          messages: s.messages.map(m =>
            m.id === newAiMsgId
              ? { ...m, content: fullText, sources, isStreaming: false, statusStep: null, metadata: aiMetadata }
              : m,
          ),
        }
      }))
    } catch (err) {
      if (err instanceof Error && err.message === 'SESSION_EXPIRED') {
        toast.error('Your session has expired. Please sign in again.')
      } else {
        toast.error('Failed to regenerate. Please try again.')
      }
      console.error('Streaming error:', err)
    } finally {
      setIsStreaming(false)
    }
  }, [activeId, isStreaming, sessions])

  // ── Feedback ──────────────────────────────────────────────────────────────
  const handleFeedback = useCallback(async (messageId: string, rating: FeedbackRating) => {
    try {
      await submitFeedback(messageId, rating)
      setSessions(prev => prev.map(s => {
        if (s.id !== activeId) return s
        return {
          ...s,
          messages: s.messages.map(m =>
            m.id === messageId ? { ...m, feedback: rating } : m
          ),
        }
      }))
    } catch {
      toast.error('Could not save feedback.')
    }
  }, [activeId])

  // ── Disambiguation selection ──────────────────────────────────────────────
  const handleDisambiguationSelect = useCallback(async (
    aiMsgId: string,
    question: string,
    selectedScope: ChatScope,
    bypass: boolean,
  ) => {
    if (isStreaming) return
    setIsStreaming(true)

    const currentSession = sessions.find(s => s.id === activeId)
    // Domain selection → new session with domain scope (session_id: null forces fresh session).
    // Bypass (search all) → reuse existing session so history is preserved.
    const sessionIdToUse = bypass ? (currentSession?.backendId ?? null) : null

    setSessions(prev => prev.map(s => {
      if (s.id !== activeId) return s
      return {
        ...s,
        messages: s.messages.map(m =>
          m.id === aiMsgId
            ? { ...m, content: '', isStreaming: true, requiresSelection: false, selectionDomains: undefined, statusStep: null }
            : m
        ),
      }
    }))

    try {
      let fullText = ''
      let sources: SourceCitation[] = []
      let newBackendSessionId: string | null = null
      let returnedScope: ChatScope | null = null
      let aiMetadata: AIResponseMetadata | null = null

      for await (const evt of streamChatQuery(question, sessionIdToUse, selectedScope, responseMode, bypass)) {
        if (evt.event === 'status') {
          setSessions(prev => prev.map(s => {
            if (s.id !== activeId) return s
            return {
              ...s,
              messages: s.messages.map(m =>
                m.id === aiMsgId
                  ? { ...m, statusStep: evt.data.step as StatusStep, statusLabel: evt.data.label }
                  : m
              ),
            }
          }))
        } else if (evt.event === 'token') {
          fullText += evt.data.text
          setSessions(prev => prev.map(s => {
            if (s.id !== activeId) return s
            return {
              ...s,
              messages: s.messages.map(m =>
                m.id === aiMsgId
                  ? { ...m, content: fullText, statusStep: null }
                  : m
              ),
            }
          }))
        } else if (evt.event === 'sources') {
          sources = evt.data.sources ?? []
          if (evt.data.session_id) newBackendSessionId = evt.data.session_id
        } else if (evt.event === 'metadata') {
          aiMetadata = evt.data as AIResponseMetadata
        } else if (evt.event === 'provider_warning') {
          console.warn('[Chat] Provider warning:', evt.data.message)
        } else if (evt.event === 'not_found') {
          console.warn('[Chat] Retrieval gate blocked response:', evt.data)
        } else if (evt.event === 'done') {
          if (evt.data.session_id) newBackendSessionId = evt.data.session_id
          if (evt.data.scope_type) {
            returnedScope = {
              type: evt.data.scope_type as ChatScope['type'],
              id:   evt.data.scope_id ?? null,
              name: evt.data.scope_name ?? null,
            }
          }
        } else if (evt.event === 'confidence') {
          setSessions(prev => prev.map(s => {
            if (s.id !== activeId) return s
            return {
              ...s,
              messages: s.messages.map(m =>
                m.id === aiMsgId
                  ? { ...m, confidence: evt.data.score, confidenceLevel: evt.data.level }
                  : m
              ),
            }
          }))
        } else if (evt.event === 'error') {
          console.error('Streaming error:', evt.data)
          toast.error(evt.data.message ?? 'Something went wrong.')
          break
        }
      }

      setSessions(prev => prev.map(s => {
        if (s.id !== activeId) return s
        return {
          ...s,
          backendId: newBackendSessionId ?? s.backendId,
          scope:     returnedScope ?? s.scope,
          messages:  s.messages.map(m =>
            m.id === aiMsgId
              ? { ...m, content: fullText, sources, isStreaming: false, statusStep: null, responseMode, metadata: aiMetadata }
              : m,
          ),
        }
      }))

      queryClient.invalidateQueries({ queryKey: ['queries'] })
      queryClient.invalidateQueries({ queryKey: ['stats']   })

    } catch (err) {
      setSessions(prev => prev.map(s =>
        s.id === activeId
          ? {
              ...s,
              messages: s.messages.map(m =>
                m.id === aiMsgId
                  ? { ...m, isStreaming: false, requiresSelection: false, content: '' }
                  : m
              ),
            }
          : s,
      ))
      if (err instanceof Error && err.message === 'SESSION_EXPIRED') {
        toast.error('Your session has expired. Please sign in again.')
      } else {
        toast.error('Failed to get a response. Please try again.')
      }
      console.error('Streaming error:', err)
    } finally {
      setIsStreaming(false)
    }
  }, [activeId, isStreaming, sessions, queryClient, responseMode])

  // ── Session management ────────────────────────────────────────────────────
  function createNewSession() {
    const s = newSession()
    setSessions(prev => [s, ...prev])
    setActiveId(s.id)
    setInput('')
    inputRef.current?.focus()
  }

  function deleteSession(id: string) {
    setSessions(prev => {
      const next = prev.filter(s => s.id !== id)
      if (next.length === 0) {
        const fresh = newSession()
        setActiveId(fresh.id)
        return [fresh]
      }
      if (id === activeId) setActiveId(next[0].id)
      return next
    })
  }

  const handleRenameSession = useCallback(async (id: string, title: string) => {
    setSessions(prev => prev.map(s => s.id === id ? { ...s, title } : s))
    const session = sessions.find(s => s.id === id)
    if (session?.backendId) {
      try {
        await updateSession(session.backendId, { title })
      } catch {
        toast.error('Could not save rename.')
      }
    }
  }, [sessions])

  const handlePinSession = useCallback(async (id: string) => {
    const session = sessions.find(s => s.id === id)
    if (!session) return
    const newPinned = !session.pinned
    setSessions(prev => prev.map(s => s.id === id ? { ...s, pinned: newPinned } : s))
    if (session.backendId) {
      try {
        await updateSession(session.backendId, { pinned: newPinned })
      } catch {
        toast.error('Could not save pin state.')
        setSessions(prev => prev.map(s => s.id === id ? { ...s, pinned: !newPinned } : s))
      }
    }
  }, [sessions])

  const isEmpty = activeSession.messages.length === 0
  const suggestedPrompts = getSuggestedPrompts(activeSession.scope)

  // Last assistant message index (for regenerate button)
  const lastAiMsgIndex = activeSession.messages.reduceRight(
    (found, m, i) => found === -1 && m.role === 'assistant' ? i : found,
    -1,
  )

  return (
    <div className="flex h-full">
      <ChatSidebar
        sessions={sessions}
        activeId={activeId}
        onSelectSession={setActiveId}
        onNewSession={createNewSession}
        onDeleteSession={deleteSession}
        onRenameSession={handleRenameSession}
        onPinSession={handlePinSession}
      />

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Context + mode bar */}
        <div className="flex items-center gap-2 px-4 py-2 border-b bg-background shrink-0 flex-wrap">
          <span className="text-xs text-muted-foreground font-medium">Context:</span>
          <ContextSelector
            value={activeSession.scope}
            onChange={updateScope}
            locked={scopeLocked}
          />
          {scopeLocked && (
            <span className="text-[10px] text-muted-foreground">Locked</span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-muted-foreground font-medium">Mode:</span>
            <ResponseModeSelector
              value={responseMode}
              onChange={setResponseMode}
              disabled={isStreaming}
            />
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {sessionLoading ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
              <Loader2 className="w-8 h-8 animate-spin text-primary" />
              <p className="text-sm">Loading conversation…</p>
            </div>
          ) : isEmpty ? (
            <div className="flex flex-col items-center justify-center h-full gap-6 text-center max-w-lg mx-auto">
              <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center">
                <Sparkles className="w-7 h-7 text-primary" />
              </div>
              <div>
                <h2 className="text-xl font-semibold">
                  {activeSession.scope.type === 'document' && activeSession.scope.name
                    ? `Chatting with ${activeSession.scope.name}`
                    : activeSession.scope.type === 'folder' && activeSession.scope.name
                    ? `Chatting with folder: ${activeSession.scope.name}`
                    : 'Ask anything about your documents'
                  }
                </h2>
                <p className="text-muted-foreground text-sm mt-1">
                  {activeSession.scope.type === 'all'
                    ? 'I can search across all your uploaded documents and give precise answers.'
                    : activeSession.scope.type === 'folder'
                    ? `I will answer using only documents in the "${activeSession.scope.name}" folder.`
                    : 'I will answer using only this document.'
                  }
                </p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full">
                {suggestedPrompts.map(prompt => (
                  <button
                    key={prompt}
                    onClick={() => sendMessage(prompt)}
                    className="text-left px-4 py-3 rounded-lg border border-border hover:border-primary/50 hover:bg-primary/5 transition-colors text-sm"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {activeSession.messages.map((msg, msgIndex) => (
                <div
                  key={msg.id}
                  className={cn('flex gap-3 message-enter', msg.role === 'user' ? 'flex-row-reverse' : 'flex-row')}
                >
                  {/* Avatar */}
                  <div className={cn(
                    'w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5',
                    msg.role === 'user' ? 'bg-primary' : 'bg-primary/10',
                  )}>
                    {msg.role === 'user'
                      ? <User className="w-4 h-4 text-white" />
                      : <Bot  className="w-4 h-4 text-primary" />
                    }
                  </div>

                  {/* Bubble + meta */}
                  <div className={cn(
                    'flex flex-col gap-1 max-w-[78%]',
                    msg.role === 'user' ? 'items-end' : 'items-start',
                  )}>
                    <div className={cn(
                      'px-4 py-3 rounded-2xl relative group/bubble',
                      msg.role === 'user'
                        ? 'bg-primary text-white rounded-tr-sm text-sm leading-relaxed whitespace-pre-wrap'
                        : 'bg-card border rounded-tl-sm',
                    )}>
                      {msg.role === 'user' ? (
                        <>
                          {msg.content}
                          {msg.isStreaming && (
                            <span className="inline-block w-1.5 h-4 ml-0.5 bg-current animate-pulse rounded-sm align-text-bottom" />
                          )}
                        </>
                      ) : (() => {
                        // Domain disambiguation selector
                        if (msg.requiresSelection && msg.selectionDomains) {
                          return (
                            <DomainSelector
                              message={msg.selectionDomains.length > 0
                                ? 'I found this topic across multiple knowledge domains. Please choose the domain you\'d like me to answer from:'
                                : 'I could not find relevant information in your documents.'}
                              domains={msg.selectionDomains}
                              onSelect={(domainName) =>
                                handleDisambiguationSelect(
                                  msg.id,
                                  msg.selectionQuestion ?? '',
                                  { type: 'domain', id: null, name: domainName },
                                  false,
                                )
                              }
                              onSearchAll={() =>
                                handleDisambiguationSelect(
                                  msg.id,
                                  msg.selectionQuestion ?? '',
                                  { type: 'all', id: null, name: null },
                                  true,
                                )
                              }
                              disabled={isStreaming}
                            />
                          )
                        }

                        // Show status indicator while waiting for first token
                        if (msg.isStreaming && !msg.content && msg.statusStep) {
                          return (
                            <div className="px-1 py-1">
                              <StatusIndicator step={msg.statusStep} label={msg.statusLabel ?? undefined} />
                            </div>
                          )
                        }

                        const { mainContent, questions } = msg.isStreaming
                          ? { mainContent: msg.content, questions: [] }
                          : extractRelatedQuestions(msg.content)

                        const meta = msg.metadata

                        return (
                          <>
                            <div className="ai-response">
                              <MarkdownRenderer content={mainContent} />
                              {msg.isStreaming && (
                                <span className="inline-block w-1.5 h-3.5 ml-0.5 bg-foreground/50 animate-pulse rounded-sm" />
                              )}
                            </div>

                            {/* Rich response addenda (shown after streaming) */}
                            {!msg.isStreaming && meta && (
                              <>
                                {meta.chart_data && (
                                  <AIChartResponse data={meta.chart_data} />
                                )}
                                {meta.timeline_events && meta.timeline_events.length > 0 && (
                                  <AITimelineResponse events={meta.timeline_events} />
                                )}
                              </>
                            )}

                            {/* Rich citations */}
                            {!msg.isStreaming && (msg.sources?.length ?? 0) > 0 && (
                              <AISourceReferences sources={msg.sources!} />
                            )}

                            {!msg.isStreaming && mainContent && (
                              <div className="absolute top-2 right-2 opacity-0 group-hover/bubble:opacity-100 transition-opacity flex items-center gap-1">
                                <ExportButton
                                  content={mainContent}
                                  filename={`response-${msg.id.slice(0, 8)}`}
                                />
                                <CopyResponseButton content={mainContent} />
                              </div>
                            )}

                            {!msg.isStreaming && questions.length > 0 && (
                              <RelatedQuestions
                                questions={questions}
                                onAsk={sendMessage}
                                disabled={isStreaming}
                              />
                            )}
                          </>
                        )
                      })()}
                    </div>

                    {/* Confidence + response type + answer length badges */}
                    {msg.role === 'assistant' && !msg.isStreaming && (
                      <div className="flex items-center gap-1.5 flex-wrap px-1">
                        {msg.confidence != null && (
                          <ConfidenceBadge
                            score={msg.confidence}
                            level={msg.confidenceLevel ?? levelFromScore(msg.confidence)}
                          />
                        )}
                        {msg.metadata?.response_type && msg.metadata.response_type !== 'text' && (
                          <ResponseTypeBadge type={msg.metadata.response_type} />
                        )}
                        {msg.metadata?.answer_type && msg.metadata.answer_type !== 'medium' && (
                          <span className={cn(
                            'text-[10px] px-1.5 py-0.5 rounded-full border font-medium',
                            msg.metadata.answer_type === 'short'
                              ? 'border-emerald-300/60 text-emerald-700 bg-emerald-50 dark:bg-emerald-950/30 dark:text-emerald-400'
                              : msg.metadata.answer_type === 'detailed'
                              ? 'border-blue-300/60 text-blue-700 bg-blue-50 dark:bg-blue-950/30 dark:text-blue-400'
                              : 'border-violet-300/60 text-violet-700 bg-violet-50 dark:bg-violet-950/30 dark:text-violet-400',
                          )}>
                            {msg.metadata.answer_type === 'short'      ? 'Concise'
                              : msg.metadata.answer_type === 'detailed'     ? 'Detailed'
                              : 'Comprehensive'}
                          </span>
                        )}
                      </div>
                    )}

                    {/* Feedback + Regenerate row */}
                    {msg.role === 'assistant' && !msg.isStreaming && msg.content && (
                      <div className="flex items-center gap-2 px-1">
                        <FeedbackButtons
                          messageId={msg.id}
                          currentFeedback={msg.feedback}
                          onFeedback={handleFeedback}
                        />
                        {/* Regenerate button only on the last AI message */}
                        {msgIndex === lastAiMsgIndex && activeSession.backendId && (
                          <button
                            onClick={regenerate}
                            disabled={isStreaming}
                            className={cn(
                              'flex items-center gap-1 text-[10px] text-muted-foreground/60',
                              'hover:text-muted-foreground transition-colors px-1 py-0.5 rounded',
                              'hover:bg-muted/50',
                              isStreaming && 'opacity-40 cursor-not-allowed',
                            )}
                            title="Regenerate response"
                          >
                            <RefreshCw className="w-3 h-3" />
                            <span>Regenerate</span>
                          </button>
                        )}
                      </div>
                    )}

                    <span className="text-xs text-muted-foreground px-1">
                      {formatRelativeTime(msg.timestamp)}
                    </span>
                  </div>
                </div>
              ))}

              {isStreaming && activeSession.messages.at(-1)?.role !== 'assistant' && (
                <TypingIndicator />
              )}
            </>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="px-6 py-4 border-t bg-background shrink-0">
          <form
            onSubmit={e => { e.preventDefault(); sendMessage(input) }}
            className="flex gap-3 items-end"
          >
            <div className="flex-1 relative">
              <Input
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input) }
                }}
                placeholder={
                  activeSession.scope.type === 'document' && activeSession.scope.name
                    ? `Ask about ${activeSession.scope.name}…`
                    : activeSession.scope.type === 'folder' && activeSession.scope.name
                    ? `Ask about the ${activeSession.scope.name} folder…`
                    : 'Ask anything about your documents…'
                }
                className="pr-4 h-11 text-sm rounded-xl"
                disabled={isStreaming}
              />
            </div>
            <SavedPromptsPanel
              onUsePrompt={text => setInput(text)}
              disabled={isStreaming}
            />
            <Button
              type="submit"
              size="icon"
              className="h-11 w-11 rounded-xl shrink-0"
              disabled={!input.trim() || isStreaming}
            >
              <Send className="w-4 h-4" />
            </Button>
          </form>
          <p className="text-xs text-muted-foreground text-center mt-2">
            Answers are based strictly on your uploaded documents.
          </p>
        </div>
      </div>
    </div>
  )
}
