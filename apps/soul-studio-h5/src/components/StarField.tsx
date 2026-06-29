// components/StarField.tsx - 星光粒子背景
import { useMemo } from 'react'

interface StarFieldProps {
  count?: number
  className?: string
}

export default function StarField({ count = 30, className = '' }: StarFieldProps) {
  const stars = useMemo(() => {
    return Array.from({ length: Math.min(count, 10) }).map((_, i) => {
      const size = Math.random() * 1.2 + 0.5
      const left = Math.random() * 100
      const top = Math.random() * 100
      const delay = Math.random() * 4
      const duration = 5 + Math.random() * 4
      const symbol = Math.random() > 0.5 ? '✦' : '✧'
      const opacity = 0.1 + Math.random() * 0.16
      return { i, size, left, top, delay, duration, symbol, opacity }
    })
  }, [count])

  return (
    <div className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}>
      {stars.map(s => (
        <span
          key={s.i}
          className="star-particle twinkle"
          style={{
            left: `${s.left}%`,
            top: `${s.top}%`,
            fontSize: `${s.size * 4}px`,
            animationDelay: `${s.delay}s`,
            animationDuration: `${s.duration}s`,
            opacity: s.opacity,
          }}
        >
          {s.symbol}
        </span>
      ))}
    </div>
  )
}
