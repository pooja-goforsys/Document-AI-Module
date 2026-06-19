import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Mail, ArrowLeft, Loader2, CheckCircle2, FileText } from 'lucide-react'

import { authApi } from '@/services/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

export default function ForgotPasswordPage() {
  const [email,     setEmail]     = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [devToken,  setDevToken]  = useState<string | null>(null)
  const [error,     setError]     = useState('')

  async function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault()
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError('Enter a valid email address')
      return
    }

    setIsLoading(true)
    setError('')
    try {
      const res = await authApi.forgotPassword(email)
      setDevToken(res._dev_reset_token ?? null)
      setSubmitted(true)
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-6">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
        className="w-full max-w-md"
      >
        {/* Logo */}
        <Link to="/login" className="flex items-center gap-2 mb-10 w-fit">
          <div className="w-8 h-8 bg-primary/10 rounded-lg flex items-center justify-center">
            <FileText className="w-4 h-4 text-primary" />
          </div>
          <span className="font-bold text-lg">DocAI</span>
        </Link>

        {!submitted ? (
          <div className="bg-card border rounded-2xl p-8 shadow-sm">
            <div className="mb-6">
              <div className="w-12 h-12 bg-primary/10 rounded-2xl flex items-center justify-center mb-4">
                <Mail className="w-6 h-6 text-primary" />
              </div>
              <h1 className="text-2xl font-bold text-foreground">Forgot your password?</h1>
              <p className="text-muted-foreground text-sm mt-2">
                Enter your email and we'll send you a reset link.
              </p>
            </div>

            {error && (
              <div className="mb-4 p-3 bg-destructive/10 border border-destructive/20 rounded-lg">
                <p className="text-destructive text-sm">{error}</p>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4" noValidate>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">Email address</label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                  <Input
                    type="email"
                    placeholder="you@example.com"
                    value={email}
                    autoFocus
                    onChange={(e) => { setEmail(e.target.value); setError('') }}
                    className={cn('pl-9 h-10', error && 'border-destructive focus-visible:ring-destructive')}
                  />
                </div>
              </div>

              <Button type="submit" className="w-full h-10" disabled={isLoading}>
                {isLoading
                  ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Sending…</>
                  : 'Send reset link'
                }
              </Button>
            </form>

            <div className="mt-5 text-center">
              <Link
                to="/login"
                className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                Back to sign in
              </Link>
            </div>
          </div>
        ) : (
          <div className="bg-card border rounded-2xl p-8 shadow-sm text-center">
            <div className="w-14 h-14 bg-green-100 dark:bg-green-900/30 rounded-2xl flex items-center justify-center mx-auto mb-4">
              <CheckCircle2 className="w-7 h-7 text-green-600 dark:text-green-400" />
            </div>
            <h1 className="text-xl font-bold text-foreground mb-2">Check your email</h1>
            <p className="text-muted-foreground text-sm mb-6">
              We sent a password reset link to <span className="font-medium text-foreground">{email}</span>.
              The link expires in 1 hour.
            </p>

            {devToken && (
              <div className="mb-6 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl text-left">
                <p className="text-xs font-semibold text-amber-700 dark:text-amber-400 mb-1">
                  Development mode — reset token:
                </p>
                <Link
                  to={`/reset-password?token=${devToken}`}
                  className="text-xs text-primary hover:underline break-all font-mono"
                >
                  /reset-password?token={devToken}
                </Link>
              </div>
            )}

            <Link to="/login">
              <Button variant="outline" className="w-full h-10">
                <ArrowLeft className="w-4 h-4 mr-2" />
                Back to sign in
              </Button>
            </Link>
          </div>
        )}
      </motion.div>
    </div>
  )
}
