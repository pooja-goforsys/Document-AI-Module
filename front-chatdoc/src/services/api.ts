import axios from 'axios'
import type {
  Document, Folder, DashboardStats, RecentQuery,
  Notification, NotificationListResponse, AuthUser,
  SavedPrompt, SavedPromptCreate, SavedPromptUpdate,
  AIResponseMetadata,
} from '../types'

export const API_BASE = 'http://localhost:8000'

// ─── Token storage ─────────────────────────────────────────────────────────────

const AT_KEY = 'docai_at'
const RT_KEY = 'docai_rt'

export function getAccessToken(): string | null {
  return localStorage.getItem(AT_KEY) ?? sessionStorage.getItem(AT_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(RT_KEY) ?? sessionStorage.getItem(RT_KEY)
}

export function storeTokens(at: string, rt: string, persistent: boolean): void {
  const store = persistent ? localStorage : sessionStorage
  store.setItem(AT_KEY, at)
  store.setItem(RT_KEY, rt)
}

export function clearTokens(): void {
  for (const store of [localStorage, sessionStorage]) {
    store.removeItem(AT_KEY)
    store.removeItem(RT_KEY)
  }
}

// ─── Axios instance ────────────────────────────────────────────────────────────

const api = axios.create({ baseURL: `${API_BASE}/api/v1` })

// Attach Bearer token to every request
api.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Handle 401 → refresh → retry
let _isRefreshing = false
let _queue: Array<{ resolve: (t: string) => void; reject: (e: unknown) => void }> = []
let _logoutCb: (() => void) | null = null

export function setApiLogoutCallback(cb: () => void): void {
  _logoutCb = cb
}

function _flushQueue(err: unknown, token: string | null) {
  _queue.forEach(({ resolve, reject }) => (err ? reject(err) : resolve(token!)))
  _queue = []
}

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config
    const url = String(original?.url ?? '')
    const isAuthEndpoint = /\/auth\/(login|signup|forgot-password|reset-password|refresh)$/.test(url)
    if (isAuthEndpoint) {
      return Promise.reject(err)
    }

    if (err.response?.status !== 401 || original._retry) {
      return Promise.reject(err)
    }

    if (_isRefreshing) {
      return new Promise<string>((resolve, reject) => {
        _queue.push({ resolve, reject })
      }).then((token) => {
        original.headers.Authorization = `Bearer ${token}`
        return api(original)
      })
    }

    original._retry = true
    _isRefreshing = true

    const rt = getRefreshToken()
    if (!rt) {
      _isRefreshing = false
      _logoutCb?.()
      return Promise.reject(err)
    }

    try {
      const { data } = await axios.post(`${API_BASE}/api/v1/auth/refresh`, {
        refresh_token: rt,
      })
      const newAt: string = data.access_token
      const persistent = !!localStorage.getItem(AT_KEY)
      storeTokens(newAt, data.refresh_token, persistent)
      api.defaults.headers.common.Authorization = `Bearer ${newAt}`
      _flushQueue(null, newAt)
      original.headers.Authorization = `Bearer ${newAt}`
      return api(original)
    } catch (refreshErr) {
      _flushQueue(refreshErr, null)
      _logoutCb?.()
      return Promise.reject(refreshErr)
    } finally {
      _isRefreshing = false
    }
  },
)

// ─── Auth ──────────────────────────────────────────────────────────────────────

export interface SignupPayload {
  full_name: string
  email: string
  password: string
  confirm_password: string
}

export interface LoginPayload {
  email: string
  password: string
  remember_me?: boolean
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: AuthUser
}

export const authApi = {
  signup: async (payload: SignupPayload): Promise<TokenResponse> => {
    const { data } = await api.post<TokenResponse>('/auth/signup', payload)
    return data
  },
  login: async (payload: LoginPayload): Promise<TokenResponse> => {
    const { data } = await api.post<TokenResponse>('/auth/login', payload)
    return data
  },
  logout: async (): Promise<void> => {
    await api.post('/auth/logout').catch(() => {})
  },
  getMe: async (): Promise<AuthUser> => {
    const { data } = await api.get<AuthUser>('/auth/me')
    return data
  },
  refresh: async (refreshToken: string): Promise<TokenResponse> => {
    const { data } = await axios.post<TokenResponse>(`${API_BASE}/api/v1/auth/refresh`, {
      refresh_token: refreshToken,
    })
    return data
  },
  forgotPassword: async (email: string): Promise<{ message: string; _dev_reset_token?: string }> => {
    const { data } = await api.post('/auth/forgot-password', { email })
    return data
  },
  resetPassword: async (token: string, new_password: string, confirm_password: string): Promise<void> => {
    await api.post('/auth/reset-password', { token, new_password, confirm_password })
  },
}

// ─── Upload ────────────────────────────────────────────────────────────────────

export async function uploadDocument(
  file: File,
  folderId?: string | null,
  onProgress?: (pct: number) => void,
): Promise<Document> {
  const form = new FormData()
  form.append('file', file)
  if (folderId) form.append('folder_id', folderId)
  const { data } = await api.post<Document>('/documents/upload', form, {
    onUploadProgress: (evt) => {
      if (onProgress && evt.total) {
        onProgress(Math.min(99, Math.round((evt.loaded / evt.total) * 100)))
      }
    },
  })
  return data
}

// ─── Documents ─────────────────────────────────────────────────────────────────

export async function getDocuments(folderId?: string | null): Promise<Document[]> {
  const params: Record<string, string> = {}
  if (folderId) params.folder_id = folderId
  const { data } = await api.get<Document[]>('/documents/', { params })
  return data
}

export async function deleteDocument(docId: string): Promise<void> {
  await api.delete(`/documents/${docId}`)
}

export async function reindexDocument(docId: string): Promise<void> {
  await api.post(`/documents/${docId}/reindex`)
}

export interface SummarizeResponse {
  document_id?: string
  document_name?: string
  folder_id?: string
  folder_name?: string
  scope: string
  summary: string
}

export async function summarizeDocument(
  docId: string,
  scope: 'full' | 'executive' | 'key_takeaways' = 'full',
): Promise<SummarizeResponse> {
  const { data } = await api.post<SummarizeResponse>(`/documents/${docId}/summarize`, { scope })
  return data
}

export async function updateDocument(
  docId: string,
  body: { name?: string; folder_id?: string | null },
): Promise<Document> {
  const { data } = await api.patch<Document>(`/documents/${docId}`, body)
  return data
}

export async function replaceDocumentFile(docId: string, file: File): Promise<Document> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.put<Document>(`/documents/${docId}/file`, form)
  return data
}

// ─── Folders ───────────────────────────────────────────────────────────────────

export async function getFolders(): Promise<Folder[]> {
  const { data } = await api.get<Folder[]>('/folders/')
  return data
}

export async function createFolder(name: string): Promise<Folder> {
  const { data } = await api.post<Folder>('/folders/', { name })
  return data
}

export async function renameFolder(id: string, name: string): Promise<Folder> {
  const { data } = await api.patch<Folder>(`/folders/${id}`, { name })
  return data
}

export async function deleteFolder(id: string): Promise<void> {
  await api.delete(`/folders/${id}`)
}

// ─── Stats ─────────────────────────────────────────────────────────────────────

export async function getStats(): Promise<DashboardStats> {
  const { data } = await api.get<DashboardStats>('/stats')
  return data
}

// ─── File access ───────────────────────────────────────────────────────────────

export function getDocumentFileUrl(docId: string): string {
  const token = getAccessToken()
  const query = token ? `?token=${encodeURIComponent(token)}` : ''
  return `${API_BASE}/api/v1/documents/${docId}/file${query}`
}

// ─── Recent queries ────────────────────────────────────────────────────────────

export async function getRecentQueries(limit = 10): Promise<RecentQuery[]> {
  const { data } = await api.get<RecentQuery[]>(`/queries/recent?limit=${limit}`)
  return data
}

// ─── Chat sessions ─────────────────────────────────────────────────────────────

export interface BackendMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources: import('../types').SourceCitation[]
  created_at: string
  confidence_score?: number | null
  response_mode?: import('../types').ResponseMode | null
}

export async function getSessionMessages(sessionId: string): Promise<BackendMessage[]> {
  const { data } = await api.get<BackendMessage[]>(`/chat/sessions/${sessionId}/messages`)
  return data
}

// ─── Chat (SSE streaming) ──────────────────────────────────────────────────────

export interface SSETokenEvent         { text: string }
export interface SSESourcesEvent       { sources: import('../types').SourceCitation[]; success: boolean; session_id?: string; message?: string; error_type?: string }
export interface SSEDoneEvent          { session_id: string; scope_type?: string; scope_id?: string | null; scope_name?: string | null; response_mode?: string }
export interface SSEErrorEvent         { message: string; error_type?: string }
export interface SSEConfidenceEvent    { score: number; level: string }
export interface SSEStatusEvent        { step: string; label: string }
export type SSEMetadataEvent = AIResponseMetadata
export interface SSEProviderWarningEvent { degraded?: boolean; message: string; error_type?: string; fix?: string; providers_tried?: string[] }
export interface SSENotFoundEvent      { reason?: string; scores?: unknown; threshold?: unknown }
export interface SSEClarificationEvent {
  requires_domain_selection: boolean
  message: string
  domains: import('../types').SelectionDomain[]
}

export type SSEEvent =
  | { event: 'token';         data: SSETokenEvent         }
  | { event: 'sources';       data: SSESourcesEvent       }
  | { event: 'done';          data: SSEDoneEvent          }
  | { event: 'error';         data: SSEErrorEvent         }
  | { event: 'confidence';    data: SSEConfidenceEvent    }
  | { event: 'status';        data: SSEStatusEvent        }
  | { event: 'metadata';      data: SSEMetadataEvent      }
  | { event: 'provider_warning'; data: SSEProviderWarningEvent }
  | { event: 'not_found';     data: SSENotFoundEvent      }
  | { event: 'clarification'; data: SSEClarificationEvent }

export interface BackendSession {
  id: string
  title: string
  scope_type: string
  scope_id: string | null
  scope_name: string | null
  pinned: boolean
  created_at: string
  updated_at: string
  message_count: number
  last_message_preview: string | null
}

export async function getChatSessions(): Promise<BackendSession[]> {
  const { data } = await api.get<BackendSession[]>('/chat/sessions')
  return data
}

export async function getSession(sessionId: string): Promise<BackendSession> {
  const { data } = await api.get<BackendSession>(`/chat/sessions/${sessionId}`)
  return data
}

export async function updateSession(
  sessionId: string,
  body: { title?: string; pinned?: boolean },
): Promise<BackendSession> {
  const { data } = await api.patch<BackendSession>(`/chat/sessions/${sessionId}`, body)
  return data
}

export async function submitFeedback(
  messageId: string,
  rating: 'like' | 'dislike',
): Promise<{ id: string; message_id: string; rating: string; created_at: string }> {
  const { data } = await api.post(`/chat/messages/${messageId}/feedback`, { rating })
  return data
}

function _getAuthHeaders(): Record<string, string> {
  const token = getAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Fetch with automatic token-refresh on 401 (mirrors the axios interceptor).
// Returns a successful Response or throws:
//   - Error('SESSION_EXPIRED') — refresh failed, user has been logged out
//   - Error('HTTP <status>')   — non-401 error response
async function _fetchSse(input: RequestInfo, init: RequestInit): Promise<Response> {
  let response = await fetch(input, {
    ...init,
    headers: { ...init.headers, ..._getAuthHeaders() },
  })

  if (response.status !== 401) {
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return response
  }

  // 401 — try to refresh the token once
  const rt = getRefreshToken()
  if (!rt) {
    _logoutCb?.()
    throw new Error('SESSION_EXPIRED')
  }

  try {
    const { data } = await axios.post(`${API_BASE}/api/v1/auth/refresh`, { refresh_token: rt })
    const persistent = !!localStorage.getItem(AT_KEY)
    storeTokens(data.access_token, data.refresh_token, persistent)
    api.defaults.headers.common.Authorization = `Bearer ${data.access_token}`
  } catch {
    _logoutCb?.()
    throw new Error('SESSION_EXPIRED')
  }

  // Retry with new token
  response = await fetch(input, {
    ...init,
    headers: { ...init.headers, ..._getAuthHeaders() },
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response
}

export async function* streamRegenerateResponse(
  sessionId: string,
): AsyncGenerator<SSEEvent> {
  console.log('Request sent')
  const response = await _fetchSse(
    `${API_BASE}/api/v1/chat/sessions/${sessionId}/regenerate`,
    { method: 'POST', headers: { Accept: 'text/event-stream' } },
  )
  console.log('Response received')
  yield* _parseSseStream(response)
}

export async function* streamChatQuery(
  question: string,
  sessionId: string | null,
  scope?: import('../types').ChatScope,
  responseMode?: import('../types').ResponseMode,
  bypassDisambiguation?: boolean,
): AsyncGenerator<SSEEvent> {
  console.log('Request sent')
  const response = await _fetchSse(`${API_BASE}/api/v1/chat/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({
      question,
      session_id:             sessionId,
      scope_type:             scope?.type ?? 'all',
      scope_id:               scope?.id   ?? null,
      scope_name:             scope?.name ?? null,
      response_mode:          responseMode ?? 'auto',
      bypass_disambiguation:  bypassDisambiguation ?? false,
    }),
  })
  console.log('Response received')
  yield* _parseSseStream(response)
}

async function* _parseSseStream(response: Response): AsyncGenerator<SSEEvent> {
  if (!response.body) {
    const error = new Error('Streaming response body is empty.')
    console.error('Streaming error:', error)
    yield { event: 'error', data: { message: error.message } } as SSEEvent
    return
  }

  const reader  = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent = ''
  let eventCount = 0

  console.debug('[SSE] Stream opened — starting to read body')
  try {
    while (true) {
      let done: boolean
      let value: Uint8Array | undefined
      try {
        ;({ done, value } = await reader.read())
      } catch (readErr) {
        // Network error mid-stream (server closed connection abruptly).
        // Yield a synthetic error event so the caller can show a message
        // in the chat bubble rather than propagating the raw TypeError.
        console.error('Streaming error:', readErr)
        console.error('[SSE] reader.read() threw — server likely closed the connection:', readErr)
        yield { event: 'error', data: { message: 'Connection lost while streaming the response. Check server logs.' } } as SSEEvent
        return
      }
      if (done) {
        console.debug(`[SSE] Stream closed — ${eventCount} event(s) received`)
        break
      }
      const chunk = decoder.decode(value, { stream: true })
      console.log('Stream chunk:', chunk)
      buffer += chunk
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        const trimmed = line.trim()
        if (trimmed.startsWith('event:')) {
          currentEvent = trimmed.slice(6).trim()
        } else if (trimmed.startsWith('data:')) {
          const raw = trimmed.slice(5).trim()
          if (!raw || raw === '[DONE]') continue
          try {
            const parsed = JSON.parse(raw)
            eventCount++
            console.debug(`[SSE] event=${currentEvent}`, parsed)
            yield { event: currentEvent, data: parsed } as SSEEvent
          } catch (parseErr) {
            console.warn('[SSE] Skipping malformed JSON in data line:', raw, parseErr)
          }
        }
      }
    }
    const tail = buffer.trim()
    if (tail) {
      console.warn('[SSE] Stream ended with incomplete frame:', tail)
    }
  } finally {
    try { reader.cancel() } catch { /* ignore */ }
  }
}

// ─── Notifications ─────────────────────────────────────────────────────────────

export async function getNotifications(
  page = 1,
  limit = 20,
  unreadOnly = false,
): Promise<NotificationListResponse> {
  const { data } = await api.get<NotificationListResponse>('/notifications', {
    params: { page, limit, unread_only: unreadOnly },
  })
  return data
}

export async function getUnreadCount(): Promise<{ count: number }> {
  const { data } = await api.get<{ count: number }>('/notifications/unread-count')
  return data
}

export async function markNotificationRead(id: string): Promise<Notification> {
  const { data } = await api.patch<Notification>(`/notifications/${id}/read`)
  return data
}

export async function markAllNotificationsRead(): Promise<{ marked_read: number }> {
  const { data } = await api.patch<{ marked_read: number }>('/notifications/read-all')
  return data
}

export async function deleteNotification(id: string): Promise<void> {
  await api.delete(`/notifications/${id}`)
}

// ─── Saved Prompts ─────────────────────────────────────────────────────────────

export const savedPromptsApi = {
  list: async (): Promise<SavedPrompt[]> => {
    const { data } = await api.get<SavedPrompt[]>('/saved-prompts/')
    return data
  },
  create: async (payload: SavedPromptCreate): Promise<SavedPrompt> => {
    const { data } = await api.post<SavedPrompt>('/saved-prompts/', payload)
    return data
  },
  update: async (id: string, payload: SavedPromptUpdate): Promise<SavedPrompt> => {
    const { data } = await api.patch<SavedPrompt>(`/saved-prompts/${id}`, payload)
    return data
  },
  recordUse: async (id: string): Promise<void> => {
    await api.post(`/saved-prompts/${id}/use`)
  },
  delete: async (id: string): Promise<void> => {
    await api.delete(`/saved-prompts/${id}`)
  },
}
