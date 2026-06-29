// components/Waveform.tsx - 静态/动态波形条（CSS伪波形）
import { useMemo } from 'react'

interface WaveformProps {
  active?: boolean
  bars?: number
  className?: string
}

export default function Waveform({ active = false, bars = 60, className = '' }: WaveformProps) {
  const barHeights = useMemo(() => {
    return Array.from({ length: bars }).map((_, i) => {
      // 模拟音频波形
      const phase = (i / bars) * Math.PI * 4
      const h = (Math.sin(phase) * 0.4 + 0.5) * 0.6 + Math.random() * 0.4
      return Math.max(0.15, h)
    })
  }, [bars])

  return (
    <div className={`waveform ${className}`}>
      {barHeights.map((h, i) => (
        <div
          key={i}
          className={`waveform-bar ${active ? 'active' : ''}`}
          style={{
            height: `${h * 100}%`,
            ...(active ? { animation: `wave-${i % 4} 0.8s ease-in-out ${(i * 0.02)}s infinite alternate` } : {}),
          }}
        />
      ))}
      <style>{`
        @keyframes wave-0 { from { transform: scaleY(0.6); } to { transform: scaleY(1.2); } }
        @keyframes wave-1 { from { transform: scaleY(0.8); } to { transform: scaleY(1.0); } }
        @keyframes wave-2 { from { transform: scaleY(0.5); } to { transform: scaleY(1.3); } }
        @keyframes wave-3 { from { transform: scaleY(0.7); } to { transform: scaleY(1.1); } }
      `}</style>
    </div>
  )
}
