import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Eye, EyeOff, Mail, Lock, User, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { AuthBranding } from './LoginPage'

// ─── Password strength meter ───────────────────────────────────────────────────

const CRITERIA = [
  { test: /.{8,}/,                              label: '8+ characters'             },
  { test: /[A-Z]/,                              label: 'Uppercase letter'           },
  { test: /[a-z]/,                              label: 'Lowercase letter'           },
  { test: /\d/,                                 label: 'Number'                     },
  { test: /[!@#$%^&*()\-_=+\[\]{}|;:'",.<>?]/, label: 'Special character'          },
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
          <div
            key={i}
            className={cn(
              'h-1 flex-1 rounded-full transition-all duration-300',
              i < met ? colors[met - 1] : 'bg-muted',
            )}
          />
        ))}
      </div>
      <p className={cn(
        'text-xs transition-colors',
        met >= 4 ? 'text-green-600 dark:text-green-400' : 'text-muted-foreground',
      )}>
        {labels[met - 1] ?? 'Enter a password'}{met === 5 ? ' ✓' : ''}
      </p>
    </div>
  )
}

// ─── Signup page ───────────────────────────────────────────────────────────────

export default function SignupPage() {
  const navigate = useNavigate()
  const { signup } = useAuth()

  const [fullName,      setFullName]      = useState('')
  const [email,         setEmail]         = useState('')
  const [password,      setPassword]      = useState('')
  const [confirmPwd,    setConfirmPwd]    = useState('')
  const [showPassword,  setShowPassword]  = useState(false)
  const [showConfirm,   setShowConfirm]   = useState(false)
  const [isLoading,     setIsLoading]     = useState(false)
  const [errors, setErrors] = useState<{
    fullName?: string; email?: string; password?: string; confirm?: string; general?: string
  }>({})

  function validate() {
    const e: typeof errors = {}
    if (!fullName.trim())                                  e.fullName = 'Full name is required'
    else if (fullName.trim().length < 2)                   e.fullName = 'Name must be at least 2 characters'
    if (!email)                                            e.email    = 'Email is required'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))   e.email    = 'Enter a valid email'
    if (!password)                                         e.password = 'Password is required'
    else if (CRITERIA.filter(c => c.test.test(password)).length < 5)
      e.password = 'Password does not meet all requirements'
    if (!confirmPwd)                                       e.confirm  = 'Please confirm your password'
    else if (confirmPwd !== password)                      e.confirm  = 'Passwords do not match'
    return e
  }

  async function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault()
    const e = validate()
    if (Object.keys(e).length) { setErrors(e); return }

    setIsLoading(true)
    setErrors({})
    try {
      await signup({
        full_name: fullName.trim(),
        email,
        password,
        confirm_password: confirmPwd,
      })
      toast.success('Account created! Welcome to DocAI.')
      navigate('/dashboard', { replace: true })
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      if (typeof detail === 'string') {
        setErrors({ general: detail })
      } else if (Array.isArray(detail)) {
        const msg = detail[0]?.msg ?? 'Validation error'
        setErrors({ general: msg })
      } else {
        setErrors({ general: 'Sign up failed. Please try again.' })
      }
    } finally {
      setIsLoading(false)
    }
  }

  const clearField = (field: keyof typeof errors) =>
    setErrors(p => ({ ...p, [field]: undefined }))

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
          <h1 className="text-2xl font-bold text-foreground">Create your account</h1>
          <p className="text-muted-foreground mt-1 text-sm mb-7">
            Get started with your free workspace
          </p>

          {errors.general && (
            <div className="mb-5 p-3 bg-destructive/10 border border-destructive/20 rounded-lg">
              <p className="text-destructive text-sm">{errors.general}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            {/* Full Name */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Full Name</label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                <Input
                  type="text"
                  placeholder="Jane Smith"
                  value={fullName}
                  autoComplete="name"
                  autoFocus
                  onChange={(e) => { setFullName(e.target.value); clearField('fullName') }}
                  className={cn('pl-9 h-10', errors.fullName && 'border-destructive focus-visible:ring-destructive')}
                />
              </div>
              {errors.fullName && <p className="text-xs text-destructive">{errors.fullName}</p>}
            </div>

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
                  onChange={(e) => { setEmail(e.target.value); clearField('email') }}
                  className={cn('pl-9 h-10', errors.email && 'border-destructive focus-visible:ring-destructive')}
                />
              </div>
              {errors.email && <p className="text-xs text-destructive">{errors.email}</p>}
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                <Input
                  type={showPassword ? 'text' : 'password'}
                  placeholder="Create a strong password"
                  value={password}
                  autoComplete="new-password"
                  onChange={(e) => { setPassword(e.target.value); clearField('password') }}
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

            {/* Confirm Password */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Confirm Password</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
                <Input
                  type={showConfirm ? 'text' : 'password'}
                  placeholder="Repeat your password"
                  value={confirmPwd}
                  autoComplete="new-password"
                  onChange={(e) => { setConfirmPwd(e.target.value); clearField('confirm') }}
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
                ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Creating account…</>
                : 'Create account'
              }
            </Button>
          </form>

          <p className="text-center text-sm text-muted-foreground mt-6">
            Already have an account?{' '}
            <Link to="/login" className="text-primary font-semibold hover:underline">
              Sign in
            </Link>
          </p>
        </motion.div>
      </div>
    </div>
  )
}
