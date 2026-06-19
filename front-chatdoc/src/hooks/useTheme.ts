import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark' | 'system'

function getSystemPreference(): 'light' | 'dark' {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light'
}

function resolveEffective(theme: Theme): 'light' | 'dark' {
  return theme === 'system' ? getSystemPreference() : theme
}

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle('dark', resolveEffective(theme) === 'dark')
  localStorage.setItem('theme', theme)
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() => {
    const saved = (localStorage.getItem('theme') as Theme | null) ?? 'system'
    applyTheme(saved)
    return saved
  })

  // React to OS preference changes when in system mode
  useEffect(() => {
    if (theme !== 'system') {
      applyTheme(theme)
      return
    }
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => applyTheme('system')
    mq.addEventListener('change', handler)
    applyTheme('system')
    return () => mq.removeEventListener('change', handler)
  }, [theme])

  const setTheme = (t: Theme) => {
    setThemeState(t)
    applyTheme(t)
  }

  const toggle = () => setTheme(theme === 'dark' ? 'light' : 'dark')

  return { theme, setTheme, toggle }
}
