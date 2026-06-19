import { useEffect, useRef, useState } from 'react'

interface AnimatedCounterProps {
  value: number
  duration?: number
  className?: string
}

export function AnimatedCounter({ value, duration = 900, className }: AnimatedCounterProps) {
  const [displayed, setDisplayed] = useState(value)
  const rafRef  = useRef<number>(0)
  const prevRef = useRef(value)

  useEffect(() => {
    const from = prevRef.current
    const to   = value
    prevRef.current = value

    if (from === to) return
    cancelAnimationFrame(rafRef.current)

    let start: number | null = null

    function tick(ts: number) {
      if (start === null) start = ts
      const t = Math.min((ts - start) / duration, 1)
      // ease-out cubic
      const eased = 1 - Math.pow(1 - t, 3)
      setDisplayed(Math.round(from + (to - from) * eased))
      if (t < 1) rafRef.current = requestAnimationFrame(tick)
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [value, duration])

  return <span className={className}>{displayed.toLocaleString()}</span>
}
