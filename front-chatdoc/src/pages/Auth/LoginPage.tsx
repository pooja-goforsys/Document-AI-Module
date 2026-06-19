import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Eye, EyeOff, Mail, Lock, Loader2,
  FileText, MessageSquare, Shield,
} from 'lucide-react'
import { toast } from 'sonner'

import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

// ─── Left branding panel (shared by all auth pages) ───────────────────────────

export function AuthBranding() {
  return (
    <div className="hidden lg:flex lg:w-[480px] shrink-0 bg-gradient-to-br from-indigo-600 via-purple-700 to-indigo-800 flex-col justify-between p-12 relative overflow-hidden">
      {/* Decorative blobs */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute -top-24 -left-24 w-96 h-96 rounded-full bg-white/10 blur-3xl" />
        <div className="absolute -bottom-24 -right-24 w-80 h-80 rounded-full bg-purple-300/20 blur-3xl" />
      </div>

      {/* Logo */}
      <div className="relative z-10 flex items-center gap-3">
        <div className="w-10 h-10 bg-white/20 backdrop-blur rounded-xl flex items-center justify-center">
          <FileText className="w-5 h-5 text-white" />
        </div>
        <span className="text-white font-bold text-xl tracking-tight">DocAI</span>
      </div>

      {/* Pitch */}
      <div className="relative z-10">
        <h2 className="text-4xl font-bold text-white leading-tight mb-4">
          Your intelligent<br />document workspace
        </h2>
        <p className="text-indigo-200 text-base mb-10 leading-relaxed">
          Upload documents, ask questions in plain language, and get instant,
          accurate AI-powered answers.
        </p>

        <div className="space-y-4">
          {([
            { icon: FileText,      text: 'Upload PDF, DOCX, XLSX & TXT files' },
            { icon: MessageSquare, text: 'Ask questions in natural language'   },
            { icon: Shield,        text: 'Your data is private and isolated'   },
          ] as const).map(({ icon: Icon, text }) => (
            <div key={text} className="flex items-center gap-3">
              <div className="w-8 h-8 bg-white/15 rounded-lg flex items-center justify-center shrink-0">
                <Icon className="w-4 h-4 text-white" />
              </div>
              <span className="text-indigo-100 text-sm">{text}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Testimonial */}
      <div className="relative z-10 bg-white/10 backdrop-blur-sm rounded-2xl p-5 border border-white/20">
        <p className="text-white/90 text-sm italic leading-relaxed">
          "DocAI transformed how I work with research papers. Finding answers now
          takes seconds, not hours."
        </p>
        <div className="flex items-center gap-2.5 mt-3">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-amber-400 to-orange-500
                          flex items-center justify-center text-white text-xs font-bold shrink-0">
            S
          </div>
          <div>
            <p className="text-white text-xs font-semibold">Sarah Chen</p>
            <p className="text-indigo-300 text-xs">Research Lead</p>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Login page ────────────────────────────────────────────────────────────────

export default function LoginPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { login } = useAuth()

  const [email,        setEmail]        = useState('')
  const [password,     setPassword]     = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [rememberMe,   setRememberMe]   = useState(false)
  const [isLoading,    setIsLoading]    = useState(false)
  const [errors, setErrors] = useState<{
    email?: string; password?: string; general?: string
  }>({})

  const redirectTo = searchParams.get('redirect') || '/dashboard'

  function validate() {
    const e: typeof errors = {}
    const normalizedEmail = email.trim()
    if (!normalizedEmail)                                       e.email    = 'Email is required'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) e.email = 'Enter a valid email'
    if (!password)                                    e.password = 'Password is required'
    return e
  }

  async function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault()
    const e = validate()
    if (Object.keys(e).length) { setErrors(e); return }

    setIsLoading(true)
    setErrors({})
    try {
      await login({ email: email.trim(), password, remember_me: rememberMe })
      toast.success('Welcome back!')
      navigate(redirectTo, { replace: true })
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Invalid email or password'
      setErrors({ general: msg })
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex bg-background">
      <AuthBranding />

      <div className="flex-1 flex items-center justify-center p-8">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
          className="w-full max-w-sm"
        >
          {/* Mobile logo */}
          <div className="flex items-center gap-2 mb-8 lg:hidden">
            <div className="w-8 h-8 bg-primary/10 rounded-lg flex items-center justify-center">
              <FileText className="w-4 h-4 text-primary" />
            </div>
            <span className="font-bold text-lg">DocAI</span>
          </div>

          <h1 className="text-2xl font-bold text-foreground">Welcome back</h1>
          <p className="text-muted-foreground mt-1 text-sm mb-7">Sign in to continue</p>

          {errors.general && (
            <div className="mb-5 p-3 bg-destructive/10 border border-destructive/20 rounded-lg">
              <p className="text-destructive text-sm">{errors.general}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            {/* Email */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Email</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                <Input
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  autoComplete="email"
                  autoFocus
                  onChange={(e) => { setEmail(e.target.value); setErrors(p => ({ ...p, email: undefined })) }}
                  className={cn('pl-9 h-10', errors.email && 'border-destructive focus-visible:ring-destructive')}
                />
              </div>
              {errors.email && <p className="text-xs text-destructive">{errors.email}</p>}
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-foreground">Password</label>
                <Link to="/forgot-password" className="text-xs text-primary hover:underline font-medium">
                  Forgot password?
                </Link>
              </div>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                <Input
                  type={showPassword ? 'text' : 'password'}
                  placeholder="Enter your password"
                  value={password}
                  autoComplete="current-password"
                  onChange={(e) => { setPassword(e.target.value); setErrors(p => ({ ...p, password: undefined })) }}
                  className={cn('pl-9 pr-10 h-10', errors.password && 'border-destructive focus-visible:ring-destructive')}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(s => !s)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {errors.password && <p className="text-xs text-destructive">{errors.password}</p>}
            </div>

            {/* Remember me */}
            <label className="flex items-center gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="w-4 h-4 rounded border-border accent-primary cursor-pointer"
              />
              <span className="text-sm text-muted-foreground">Remember me for 7 days</span>
            </label>

            <Button type="submit" className="w-full h-10" disabled={isLoading}>
              {isLoading
                ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Signing in…</>
                : 'Sign in'
              }
            </Button>
          </form>

          <p className="text-center text-sm text-muted-foreground mt-6">
            Don't have an account?{' '}
            <Link to="/signup" className="text-primary font-semibold hover:underline">
              Create one
            </Link>
          </p>
        </motion.div>
      </div>
    </div>
  )
}
