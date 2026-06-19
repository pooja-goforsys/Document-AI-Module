import React, {
  createContext, useCallback, useContext, useEffect, useReducer,
} from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'

import {
  authApi,
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setApiLogoutCallback,
  storeTokens,
  type LoginPayload,
  type SignupPayload,
} from '@/services/api'
import type { AuthUser } from '@/types'

// ─── State / actions ───────────────────────────────────────────────────────────

interface AuthState {
  user: AuthUser | null
  isLoading: boolean
}

type AuthAction =
  | { type: 'AUTH_SUCCESS'; user: AuthUser }
  | { type: 'AUTH_FAILURE' }
  | { type: 'LOGOUT' }

function reducer(state: AuthState, action: AuthAction): AuthState {
  switch (action.type) {
    case 'AUTH_SUCCESS': return { user: action.user, isLoading: false }
    case 'AUTH_FAILURE': return { user: null,        isLoading: false }
    case 'LOGOUT':       return { user: null,        isLoading: false }
    default:             return state
  }
}

// ─── Context ───────────────────────────────────────────────────────────────────

interface AuthContextType extends AuthState {
  isAuthenticated: boolean
  login: (payload: LoginPayload) => Promise<void>
  signup: (payload: SignupPayload) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

// ─── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [state, dispatch] = useReducer(reducer, { user: null, isLoading: true })

  const logout = useCallback(() => {
    clearTokens()
    dispatch({ type: 'LOGOUT' })
    // Wipe the entire React Query cache so no previous user's data
    // leaks to the next user who logs in on the same browser tab.
    queryClient.clear()
    navigate('/login', { replace: true })
  }, [navigate, queryClient])

  // Register logout callback so the axios 401-refresh interceptor can call it
  useEffect(() => {
    setApiLogoutCallback(logout)
  }, [logout])

  // On app load: attempt to restore session from stored tokens
  useEffect(() => {
    let cancelled = false

    async function initAuth() {
      const at = getAccessToken()
      const rt = getRefreshToken()

      if (!at && !rt) {
        if (!cancelled) dispatch({ type: 'AUTH_FAILURE' })
        return
      }

      // Try /auth/me with current access token
      if (at) {
        try {
          const user = await authApi.getMe()
          if (!cancelled) dispatch({ type: 'AUTH_SUCCESS', user })
          return
        } catch {
          // Access token invalid/expired — fall through to refresh
        }
      }

      // Try refresh
      if (rt) {
        try {
          const tokens = await authApi.refresh(rt)
          const persistent = !!localStorage.getItem('docai_at')
          storeTokens(tokens.access_token, tokens.refresh_token, persistent)
          if (!cancelled) dispatch({ type: 'AUTH_SUCCESS', user: tokens.user })
          return
        } catch {
          clearTokens()
        }
      }

      if (!cancelled) dispatch({ type: 'AUTH_FAILURE' })
    }

    initAuth()
    return () => { cancelled = true }
  }, [])

  const _invalidateNotifications = useCallback(() => {
    // Small delay so the backend notification is committed before we fetch
    setTimeout(() => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
    }, 600)
  }, [queryClient])

  const login = useCallback(async (payload: LoginPayload) => {
    // Clear any stale data from a previous user before loading the new one.
    queryClient.clear()
    const data = await authApi.login(payload)
    storeTokens(data.access_token, data.refresh_token, payload.remember_me ?? false)
    dispatch({ type: 'AUTH_SUCCESS', user: data.user })
    _invalidateNotifications()
  }, [_invalidateNotifications, queryClient])

  const signup = useCallback(async (payload: SignupPayload) => {
    queryClient.clear()
    const data = await authApi.signup(payload)
    storeTokens(data.access_token, data.refresh_token, true)
    dispatch({ type: 'AUTH_SUCCESS', user: data.user })
    _invalidateNotifications()
  }, [_invalidateNotifications, queryClient])

  return (
    <AuthContext.Provider value={{
      ...state,
      isAuthenticated: !!state.user,
      login,
      signup,
      logout,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
