// components/PageHeader.tsx - 页面通用头部（返回箭头 + 居中标题 + 副标题）
import { useNavigate } from 'react-router-dom'
import LiquidGlassPanel from './LiquidGlassPanel'

interface PageHeaderProps {
  title: string
  subtitle?: string
  showBack?: boolean
  deco?: boolean
  onBack?: () => void
  extra?: React.ReactNode
}

export default function PageHeader({ title, subtitle, showBack = true, deco = true, onBack, extra }: PageHeaderProps) {
  const navigate = useNavigate()
  return (
    <div className="relative z-20 px-4 pt-10 pb-4">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-white/62 to-transparent" />
      {showBack && (
        <div className="page-header__back-fixed h-10 w-10">
          <LiquidGlassPanel
            className="h-full w-full liquid-glass-panel--waterdrop"
            contentClassName="h-full"
            radius={22}
            variant="control"
            interactive
          >
            <button
              onClick={() => onBack ? onBack() : navigate(-1)}
              className="flex h-full w-full items-center justify-center text-purple-800 transition-colors hover:text-purple-950"
            >
              <span className="text-xl">←</span>
            </button>
          </LiquidGlassPanel>
        </div>
      )}
      {extra && (
        <div className="absolute right-4 top-10 z-10">
          {extra}
        </div>
      )}
      <div className="relative mx-auto max-w-[260px] text-center">
        {deco && (
          <div className="mb-1 flex items-center justify-center gap-2">
            <span className="liquid-droplet liquid-droplet--pill inline-flex items-center px-2 py-0.5 text-[10px] font-semibold tracking-[0.2em] text-purple-300">
              ✦ SOUL STUDIO ✦
            </span>
          </div>
        )}
        <h1 className="truncate text-[22px] font-black leading-tight text-soul-gradient">{title}</h1>
        {subtitle && (
          <p className="mt-1 truncate text-xs font-medium text-purple-400">{subtitle}</p>
        )}
      </div>
    </div>
  )
}
