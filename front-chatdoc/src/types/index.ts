export type FileType = 'pdf' | 'docx' | 'xlsx' | 'txt'

// ── AI response metadata (from the `metadata` SSE event) ──────────────────────

export type AIResponseType =
  | 'text'
  | 'table'
  | 'chart'
  | 'diagram'
  | 'code'
  | 'timeline'
  | 'comparison'
  | 'summary'
  | 'formula'

export interface ChartDataPoint {
  name: string
  [key: string]: string | number
}

export interface ChartData {
  type: 'bar' | 'line' | 'pie'
  title: string
  x_label?: string
  series: string[]
  data: ChartDataPoint[]
}

export interface TimelineEvent {
  date: string
  event: string
  description?: string
}

export interface AIResponseMetadata {
  response_type: AIResponseType
  answer_type?: 'short' | 'medium' | 'detailed' | 'comprehensive'
  chart_data?: ChartData
  mermaid_diagrams?: string[]
  timeline_events?: TimelineEvent[]
}

export type ResponseMode =
  | 'auto'
  | 'simple'
  | 'detailed'
  | 'technical'
  | 'summary'
  | 'bullets'
  | 'executive'

export type FeedbackRating = 'like' | 'dislike'

export type StatusStep = 'thinking' | 'searching' | 'generating'

export interface SourceCitation {
  document_id: string
  document_name: string
  page_number: number | null
  score: number
  domain_name?: string | null
  chunk_id?: string | null
  highlight_text?: string | null
}

export interface Folder {
  id: string
  name: string
  document_count: number
  created_at: string
  updated_at: string
}

export interface Document {
  id: string
  name: string
  type: FileType
  size: number
  folder_id: string | null
  folder_name: string | null
  status: string
  chunk_count: number
  page_count: number | null
  indexed: boolean
  uploaded_at: string
  indexed_at: string | null
  summary?: string | null
}

export interface SelectionDomain {
  domain_name: string
  similarity: number
  document_count: number
}

export interface ChatMessage {
  id: string
  content: string
  role: 'user' | 'assistant'
  timestamp: string
  sources?: SourceCitation[]
  isStreaming?: boolean
  confidence?: number | null
  confidenceLevel?: string | null
  responseMode?: ResponseMode | null
  feedback?: FeedbackRating | null
  statusStep?: StatusStep | null
  statusLabel?: string | null
  metadata?: AIResponseMetadata | null
  // Domain disambiguation
  requiresSelection?: boolean
  selectionDomains?: SelectionDomain[]
  selectionQuestion?: string
}

export type ScopeType = 'all' | 'folder' | 'document' | 'domain'

export interface ChatScope {
  type: ScopeType
  id: string | null
  name: string | null
}

export interface ChatSession {
  id: string
  backendId: string | null  // real UUID from backend, null until first message
  title: string
  messages: ChatMessage[]
  scope: ChatScope
  pinned: boolean
  created_at: string
  updated_at: string
}

export interface DashboardStats {
  total_documents: number
  total_folders: number
  indexed_documents: number
  ai_queries_today: number
  storage_used_mb: number
  storage_total_mb: number
}

export interface RecentQuery {
  id: string
  session_id: string
  question: string
  created_at: string
  sources: SourceCitation[]
  answer_preview?: string | null
}

// ── Auth ───────────────────────────────────────────────────────────────────────

export interface AuthUser {
  id: string
  email: string
  full_name: string | null
  is_active: boolean
  created_at: string
}

// ── Notifications ──────────────────────────────────────────────────────────────

export type NotificationType = 'document' | 'ai' | 'error' | 'system'

export interface Notification {
  id: string
  title: string
  message: string
  type: NotificationType
  is_read: boolean
  created_at: string
}

export interface NotificationListResponse {
  items: Notification[]
  total: number
  unread: number
}

// ── Saved Prompts ──────────────────────────────────────────────────────────────

export interface SavedPrompt {
  id: string
  title: string
  content: string
  response_mode: ResponseMode | null
  category: string | null
  use_count: number
  is_pinned: boolean
  created_at: string
  updated_at: string
}

export interface SavedPromptCreate {
  title: string
  content: string
  response_mode?: ResponseMode | null
  category?: string | null
}

export interface SavedPromptUpdate {
  title?: string
  content?: string
  response_mode?: ResponseMode | null
  category?: string | null
  is_pinned?: boolean
}
