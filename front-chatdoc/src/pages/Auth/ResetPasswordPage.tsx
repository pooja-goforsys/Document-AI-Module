import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Eye, EyeOff, Lock, Loader2, CheckCircle2, AlertCircle, FileText } from 'lucide-react'
import { toast } from 'sonner'

import { authApi } from '@/services/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

const CRITERIA = [
  { test: /.{8,}/,                              label: '8+ characters'    },
  { test: /[A-Z]/,                              label: 'Uppercase letter' },
  { test: /[a-z]/,                              label: 'Lowercase letter' },
  { test: /\d/,                                 label: 'Number'           },
  { test: /[!@#$%^&*()\-_=+\[\]{}|;:'",.<>?]/, label: 'Special char'     },
]

function PasswordStrength({ password }: { password: string }) {
  if (!password) return null
  const met = CRITERIA.filter(c => c.test.test(password)).length
  const colors = ['bg-red-500', 'bg-orange-500', 'bg-yellow-500', 'bg-green-500', 'bg-emerald-500']
  const labels = ['Very weak', 'Weak', 'Fair', 'Good', 'Strong']
  return (
    <div className="mt-1.5">
      <div className="flex gap-1 mb-1">
        {CRITERIA.map((_, i) => (
          <div key={i} className={cn('h-1 flex-1 rounded-full transition-all', i < met ? colors[met - 1] : 'bg-muted')} />
        ))}
      </div>
      <p className={cn('text-xs', met >= 4 ? 'text-green-600 dark:text-green-400' : 'text-muted-foreground')}>
        {labels[met - 1] ?? ''}{met === 5 ? ' ✓' : ''}
      </p>
    </div>
  )
}

export default function ResetPasswordPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [password,     setPassword]     = useState('')
  const [confirmPwd,   setConfirmPwd]   = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm,  setShowConfirm]  = useState(false)
  const [isLoading,    setIsLoading]    = useState(false)
  const [success,      setSuccess]      = useState(false)
  const [errors, setErrors] = useState<{ password?: string; confirm?: string; general?: string }>({})

  useEffect(() => {
    if (!token) navigate('/forgot-password', { replace: true })
  }, [token, navigate])

  function validate() {
    const e: typeof errors = {}
    if (!password)                                              e.password = 'Password is required'
    else if (CRITERIA.filter(c => c.test.test(password)).length < 5)
      e.password = 'Password does not meet all requirements'
    if (!confirmPwd)                                            e.confirm  = 'Please confirm your password'
    else if (confirmPwd !== password)                           e.confirm  = 'Passwords do not match'
    return e
  }

  async function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault()
    const e = validate()
    if (Object.keys(e).length) { setErrors(e); return }

    setIsLoading(true)
    setErrors({})
    try {
      await authApi.resetPassword(token, password, confirmPwd)
      setSuccess(true)
      toast.success('Password updated! Redirecting to sign in…')
      setTimeout(() => navigate('/login', { replace: true }), 2500)
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      setErrors({ general: typeof detail === 'string' ? detail : 'Reset failed. The link may have expired.' })
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

        {success ? (
          <div className="bg-card border rounded-2xl p-8 shadow-sm text-center">
            <div className="w-14 h-14 bg-green-100 dark:bg-green-900/30 rounded-2xl flex items-center justify-center mx-auto mb-4">
              <CheckCircle2 className="w-7 h-7 text-green-600 dark:text-green-400" />
            </div>
            <h1 className="text-xl font-bold text-foreground mb-2">Password updated!</h1>
            <p className="text-muted-foreground text-sm">Redirecting you to sign in…</p>
          </div>
        ) : (
          <div className="bg-card border rounded-2xl p-8 shadow-sm">
            <div className="mb-6">
              <div className="w-12 h-12 bg-primary/10 rounded-2xl flex items-center justify-center mb-4">
                <Lock className="w-6 h-6 text-primary" />
              </div>
              <h1 className="text-2xl font-bold text-foreground">Set new password</h1>
              <p className="text-muted-foreground text-sm mt-1">
                Your new password must be different from your previous one.
              </p>
            </div>

            {errors.general && (
              <div className="mb-5 p-3 bg-destructive/10 border border-destructive/20 rounded-lg flex items-start gap-2">
                <AlertCircle className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
                <p className="text-destructive text-sm">{errors.general}</p>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4" noValidate>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">New Password</label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                  <Input
                    type={showPassword ? 'text' : 'password'}
                    placeholder="Create a strong password"
                    value={password}
                    autoFocus
                    autoComplete="new-password"
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
                <PasswordStrength password={password} />
                {errors.password && <p className="text-xs text-destructive">{errors.password}</p>}
              </div>

              <div className="space-y-1.5">
                <label className="text-sm font-medium text-foreground">Confirm New Password</label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                  <Input
                    type={showConfirm ? 'text' : 'password'}
                    placeholder="Repeat your password"
                    value={confirmPwd}
                    autoComplete="new-password"
                    onChange={(e) => { setConfirmPwd(e.target.value); setErrors(p => ({ ...p, confirm: undefined })) }}
                    className={cn('pl-9 pr-10 h-10', errors.confirm && 'border-destructive focus-visible:ring-destructive')}
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirm(s => !s)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                    tabIndex={-1}
                  >
                    {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                {errors.confirm && <p className="text-xs text-destructive">{errors.confirm}</p>}
              </div>

              <Button type="submit" className="w-full h-10" disabled={isLoading}>
                {isLoading
                  ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Updating…</>
                  : 'Update password'
                }
              </Button>
            </form>

            <div className="mt-5 text-center">
              <Link
                to="/login"
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Back to sign in
              </Link>
            </div>
          </div>
        )}
      </motion.div>
    </div>
  )
}
