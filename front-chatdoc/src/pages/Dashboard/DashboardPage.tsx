import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  FileText, Folder, CheckCircle2, MessageSquare,
  ArrowRight, Upload, Pin,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { getStats, getDocuments, getRecentQueries, getChatSessions } from '@/services/api'
import { DashboardSkeleton } from '@/components/skeletons/DashboardSkeleton'
import { AnimatedCounter } from '@/components/dashboard/AnimatedCounter'
import { QueryActivityChart } from '@/components/dashboard/QueryActivityChart'
import { DocumentRow } from '@/components/dashboard/DocumentRow'
import { ChatPreviewCard } from '@/components/dashboard/ChatPreviewCard'
import { EmptyDocumentsState } from '@/components/dashboard/EmptyDocumentsState'
import { EmptyChatsState } from '@/components/dashboard/EmptyChatsState'

const STAT_CARDS = [
  {
    key: 'total_documents' as const,
    title: 'Total Documents',
    icon: FileText,
    color: 'text-blue-600 dark:text-blue-400',
    bg:    'bg-blue-50 dark:bg-blue-900/20',
  },
  {
    key: 'total_folders' as const,
    title: 'Total Folders',
    icon: Folder,
    color: 'text-violet-600 dark:text-violet-400',
    bg:    'bg-violet-50 dark:bg-violet-900/20',
  },
  {
    key: 'indexed_documents' as const,
    title: 'Indexed Documents',
    icon: CheckCircle2,
    color: 'text-emerald-600 dark:text-emerald-400',
    bg:    'bg-emerald-50 dark:bg-emerald-900/20',
  },
  {
    key: 'ai_queries_today' as const,
    title: 'AI Queries Today',
    icon: MessageSquare,
    color: 'text-orange-600 dark:text-orange-400',
    bg:    'bg-orange-50 dark:bg-orange-900/20',
  },
] as const

export default function DashboardPage() {
  const navigate = useNavigate()
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['stats'],
    queryFn: getStats,
  })

  const { data: documents = [] } = useQuery({
    queryKey: ['documents'],
    queryFn: () => getDocuments(),
    refetchInterval: (query) => {
      const docs = (query.state.data as import('@/types').Document[] | undefined) ?? []
      return docs.some(d => d.status === 'pending' || d.status === 'indexing') ? 3000 : false
    },
    refetchIntervalInBackground: true,
  })

  // Larger limit for the activity chart (group by day)
  const { data: allRecentQueries = [] } = useQuery({
    queryKey: ['queries', 50],
    queryFn: () => getRecentQueries(50),
    refetchInterval: 15_000,
  })

  const { data: chatSessions = [] } = useQuery({
    queryKey: ['chat-sessions'],
    queryFn: getChatSessions,
    refetchInterval: 15_000,
  })

  if (statsLoading) {
    return <DashboardSkeleton />
  }

  const recentDocs = documents.slice(0, 6)

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className="flex items-center justify-between"
      >
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            Welcome back — here's what's happening with your documents.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link to="/documents">
              <Upload className="w-4 h-4 mr-1.5" />
              Upload
            </Link>
          </Button>
          <Button size="sm" asChild>
            <Link to="/chat">
              <MessageSquare className="w-4 h-4 mr-1.5" />
              Ask AI
            </Link>
          </Button>
        </div>
      </motion.div>

      {/* ── KPI Cards ──────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {STAT_CARDS.map(({ key, title, icon: Icon, color, bg }, i) => (
          <motion.div
            key={key}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: i * 0.06, ease: 'easeOut' }}
          >
            <Card className="hover:shadow-md transition-shadow h-full">
              <CardContent className="pt-6">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      {title}
                    </p>
                    <AnimatedCounter
                      value={stats?.[key] ?? 0}
                      className="text-3xl font-bold mt-1 block"
                    />
                  </div>
                  <div className={`p-2.5 rounded-lg ${bg}`}>
                    <Icon className={`w-5 h-5 ${color}`} />
                  </div>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        ))}
      </div>

      {/* ── Activity Chart + Recent Docs (2-col) ───────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Left column: activity chart + recent docs */}
        <div className="lg:col-span-2 space-y-6">

          {/* Query Activity Sparkline */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.25 }}
          >
            <Card>
              <CardContent className="pt-6">
                <QueryActivityChart
                  queries={allRecentQueries}
                  todayCount={stats?.ai_queries_today ?? 0}
                />
              </CardContent>
            </Card>
          </motion.div>

          {/* Recent Documents */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.32 }}
          >
            <Card>
              <CardHeader className="pb-3 flex flex-row items-center justify-between">
                <CardTitle className="text-base">Recent Documents</CardTitle>
                <Button variant="ghost" size="sm" asChild>
                  <Link
                    to="/documents"
                    className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                  >
                    View all <ArrowRight className="w-3 h-3" />
                  </Link>
                </Button>
              </CardHeader>
              <CardContent className="p-0">
                {recentDocs.length === 0 ? (
                  <EmptyDocumentsState />
                ) : (
                  <div className="divide-y">
                    {recentDocs.map(doc => (
                      <DocumentRow key={doc.id} doc={doc} />
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </motion.div>
        </div>

        {/* Right column: quick stats / placeholder for future widget */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.38 }}
          className="space-y-4"
        >
          <Card>
            <CardContent className="pt-6">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">
                Total Chats
              </p>
              <AnimatedCounter
                value={chatSessions.length}
                className="text-3xl font-bold block"
              />
              <p className="text-xs text-muted-foreground mt-1">
                {chatSessions.filter(s => s.pinned).length} pinned
              </p>
            </CardContent>
          </Card>
        </motion.div>

      </div>

      {/* ── All Recent Chats (full-width) ───────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.44 }}
      >
        <Card>
          <CardHeader className="pb-3 flex flex-row items-center justify-between">
            <div className="flex items-center gap-2">
              <CardTitle className="text-base">Recent Chats</CardTitle>
              {chatSessions.length > 0 && (
                <span className="text-xs bg-muted text-muted-foreground rounded-full px-2 py-0.5 font-medium">
                  {chatSessions.length}
                </span>
              )}
            </div>
            <Button size="sm" onClick={() => navigate('/chat')}>
              <MessageSquare className="w-3.5 h-3.5 mr-1.5" />
              New Chat
            </Button>
          </CardHeader>

          <CardContent className="p-0">
            {chatSessions.length === 0 ? (
              <EmptyChatsState />
            ) : (
              <>
                {/* Pinned sessions */}
                {chatSessions.some(s => s.pinned) && (
                  <div>
                    <div className="flex items-center gap-1.5 px-4 py-2 bg-muted/30">
                      <Pin className="w-3 h-3 text-amber-500 fill-amber-500" />
                      <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                        Pinned
                      </span>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 divide-y md:divide-y-0 md:gap-0">
                      {chatSessions.filter(s => s.pinned).map(s => (
                        <div key={s.id} className="border-b last:border-b-0 md:border-b md:border-r md:last:border-r-0">
                          <ChatPreviewCard session={s} />
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* All other sessions */}
                {chatSessions.some(s => !s.pinned) && (
                  <div>
                    {chatSessions.some(s => s.pinned) && (
                      <div className="px-4 py-2 bg-muted/20">
                        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                          All Chats
                        </span>
                      </div>
                    )}
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
                      {chatSessions.filter(s => !s.pinned).map((s) => (
                        <div
                          key={s.id}
                          className="border-b md:border-r [&:nth-child(2n)]:md:border-r-0 xl:[&:nth-child(2n)]:border-r xl:[&:nth-child(3n)]:border-r-0 last:border-b-0"
                        >
                          <ChatPreviewCard session={s} />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </motion.div>

    </div>
  )
}
