import { type CSSProperties, type PointerEvent, type ReactNode, useRef, useState } from 'react'
import LiquidGlass from 'liquid-glass-react'

type LiquidGlassVariant = 'panel' | 'hero' | 'nav' | 'control'

interface LiquidGlassPanelProps {
  children: ReactNode
  className?: string
  contentClassName?: string
  radius?: number
  variant?: LiquidGlassVariant
  interactive?: boolean
}

const variantConfig: Record<LiquidGlassVariant, {
  displacementScale: number
  blurAmount: number
  saturation: number
  aberrationIntensity: number
  elasticity: number
  mode: 'standard' | 'polar' | 'prominent'
}> = {
  panel: {
    displacementScale: 48,
    blurAmount: 0.018,
    saturation: 132,
    aberrationIntensity: 1.65,
    elasticity: 0.24,
    mode: 'standard',
  },
  hero: {
    displacementScale: 68,
    blurAmount: 0.022,
    saturation: 136,
    aberrationIntensity: 2.15,
    elasticity: 0.32,
    mode: 'prominent',
  },
  nav: {
    displacementScale: 62,
    blurAmount: 0.016,
    saturation: 130,
    aberrationIntensity: 1.95,
    elasticity: 0.3,
    mode: 'polar',
  },
  control: {
    displacementScale: 76,
    blurAmount: 0.016,
    saturation: 138,
    aberrationIntensity: 2.35,
    elasticity: 0.38,
    mode: 'standard',
  },
}

type PointerState = {
  global: { x: number; y: number }
  offset: { x: number; y: number }
}

export default function LiquidGlassPanel({
  children,
  className = '',
  contentClassName = '',
  radius = 28,
  variant = 'panel',
  interactive = false,
}: LiquidGlassPanelProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [pointerState, setPointerState] = useState<PointerState | null>(null)
  const config = variantConfig[variant]

  function updatePointerState(event: PointerEvent<HTMLDivElement>) {
    const rect = ref.current?.getBoundingClientRect()
    if (!rect) return

    setPointerState({
      global: { x: event.clientX, y: event.clientY },
      offset: {
        x: ((event.clientX - rect.left - rect.width / 2) / rect.width) * 100,
        y: ((event.clientY - rect.top - rect.height / 2) / rect.height) * 100,
      },
    })
  }

  return (
    <div
      ref={ref}
      className={`liquid-glass-panel liquid-glass-panel--${variant} ${interactive ? 'liquid-glass-panel--interactive' : ''} ${className}`}
      style={{ '--liquid-radius': `${radius}px` } as CSSProperties}
      onPointerMove={updatePointerState}
      onPointerDown={updatePointerState}
      onPointerLeave={() => setPointerState(null)}
    >
      <LiquidGlass
        className="liquid-glass-bg"
        cornerRadius={radius}
        displacementScale={config.displacementScale}
        blurAmount={config.blurAmount}
        saturation={config.saturation}
        aberrationIntensity={config.aberrationIntensity}
        elasticity={config.elasticity}
        mode={config.mode}
        overLight={false}
        padding="0"
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          width: '100%',
          height: '100%',
        }}
        globalMousePos={pointerState?.global}
        mouseOffset={pointerState?.offset}
        mouseContainer={ref}
      >
        <span className="liquid-glass-bg-fill" />
      </LiquidGlass>
      <div className={`liquid-glass-panel__content ${contentClassName}`}>
        {children}
      </div>
    </div>
  )
}
