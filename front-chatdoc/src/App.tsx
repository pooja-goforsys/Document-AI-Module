import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import { AlertCircle, AlertTriangle, CheckCircle2, Info } from 'lucide-react'

import { AuthProvider } from '@/contexts/AuthContext'
import { ProtectedRoute } from '@/components/auth/ProtectedRoute'
import { Layout } from '@/components/layout/Layout'

import LoginPage         from '@/pages/Auth/LoginPage'
import SignupPage        from '@/pages/Auth/SignupPage'
import ForgotPasswordPage from '@/pages/Auth/ForgotPasswordPage'
import ResetPasswordPage  from '@/pages/Auth/ResetPasswordPage'

const DashboardPage = lazy(() => import('@/pages/Dashboard/DashboardPage'))
const DocumentsPage = lazy(() => import('@/pages/Documents/DocumentsPage'))
const ChatPage = lazy(() => import('@/pages/Chat/ChatPage'))
const NotificationsPage = lazy(() => import('@/pages/Notifications/NotificationsPage'))

const preloadAppRoutes = () => {
  void import('@/pages/Dashboard/DashboardPage')
  void import('@/pages/Documents/DocumentsPage')
  void import('@/pages/Chat/ChatPage')
  void import('@/pages/Notifications/NotificationsPage')
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,
      gcTime: 1000 * 60 * 30,
      retry: 1,
      refetchOnMount: false,
      refetchOnReconnect: false,
      refetchOnWindowFocus: false,
    },
  },
})

export default function App() {
  useEffect(() => {
    const idle = window.requestIdleCallback?.(preloadAppRoutes)
    if (!idle) {
      const timeout = window.setTimeout(preloadAppRoutes, 800)
      return () => window.clearTimeout(timeout)
    }
    return () => window.cancelIdleCallback?.(idle)
  }, [])

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* ── Public auth routes ─────────────────────────────────────── */}
            <Route path="/login"           element={<LoginPage />}          />
            <Route path="/signup"          element={<SignupPage />}         />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password"  element={<ResetPasswordPage />}  />

            {/* ── Protected app routes ───────────────────────────────────── */}
            <Route element={<ProtectedRoute />}>
              <Route element={<Layout />}>
                <Route index element={<Navigate to="/dashboard" replace />} />
                <Route path="/dashboard"     element={<Suspense fallback={null}><DashboardPage /></Suspense>}     />
                <Route path="/documents"     element={<Suspense fallback={null}><DocumentsPage /></Suspense>}     />
                <Route path="/chat"          element={<Suspense fallback={null}><ChatPage /></Suspense>}          />
                <Route path="/notifications" element={<Suspense fallback={null}><NotificationsPage /></Suspense>} />
              </Route>
            </Route>

            {/* ── Fallback ───────────────────────────────────────────────── */}
            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>

          <Toaster
            position="top-right"
            richColors
            expand={false}
            icons={{
              success: <CheckCircle2 className="h-4 w-4" />,
              error:   <AlertCircle   className="h-4 w-4" />,
              warning: <AlertTriangle className="h-4 w-4" />,
              info:    <Info          className="h-4 w-4" />,
            }}
            toastOptions={{
              classNames: {
                toast:       'rounded-xl shadow-lg text-sm font-sans',
                title:       'font-medium',
                description: 'text-xs opacity-80',
              },
            }}
          />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
