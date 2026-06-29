// pages/HomePage.tsx - 屏X：我的灵偶收藏页（App 主入口）
import { useState, useEffect, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiBases, apiFigures, type FigureProfile } from '../services/api'
import StarField from '../components/StarField'
import LiquidGlassPanel from '../components/LiquidGlassPanel'

const LEVEL_COLORS: Record<string, string> = {
  '陌生': 'bg-white/70 text-purple-600 ring-1 ring-white/80',
  '熟悉': 'bg-blue-100/90 text-blue-600 ring-1 ring-blue-200/80',
  '依赖': 'bg-pink-100/90 text-pink-600 ring-1 ring-pink-200/80',
  '羁绊': 'bg-gradient-to-r from-purple-500 to-pink-500 text-white shadow-sm shadow-pink-300/40',
}

const FIGURE_PALETTES = [
  ['#7c3aed', '#ec4899', '#f8a4d8'],
  ['#5b5ff5', '#a855f7', '#d8c4ff'],
  ['#db2777', '#fb7185', '#ffd1e7'],
  ['#4338ca', '#06b6d4', '#c4f1ff'],
  ['#6d28d9', '#f59e0b', '#ffe1a8'],
]

const QUICK_ACTIONS = [
  {
    title: '召唤',
    subtitle: '创建新灵偶',
    icon: '+',
    path: '/create',
  },
  {
    title: '互动',
    subtitle: '模拟触摸',
    icon: '⌁',
    path: '/simulate',
  },
  {
    title: '对话',
    subtitle: '调试灵魂',
    icon: '◌',
    path: '/dialogue-debug',
  },
]

function getFigureArchetype(figure?: Partial<FigureProfile> | null): string {
  return figure?.soul_profile?.archetype || figure?.figure_type || '灵偶'
}

function getFigureLevel(figure?: Partial<FigureProfile> | null): string {
  return figure?.memory?.relationship_level || '陌生'
}

function getFigurePoints(figure?: Partial<FigureProfile> | null): number {
  return figure?.memory?.relationship_points || 0
}

function getFigureStreak(figure?: Partial<FigureProfile> | null): number {
  return figure?.memory?.streak_days || 0
}

function relationshipPercent(points: number) {
  return Math.min(100, Math.max(8, (points / 151) * 100))
}

function paletteStyle(seed?: string): CSSProperties {
  const code = (seed || 'soul').split('').reduce((sum, char) => sum + char.charCodeAt(0), 0)
  const palette = FIGURE_PALETTES[code % FIGURE_PALETTES.length]
  return {
    '--figure-a': palette[0],
    '--figure-b': palette[1],
    '--figure-c': palette[2],
  } as CSSProperties
}

function MetricChip({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="home-active-metric">
      <p>{label}</p>
      <strong>{value}</strong>
    </div>
  )
}

function FigureArt({ figure, mode = 'card' }: { figure?: Partial<FigureProfile> | null; mode?: 'card' | 'hero' | 'avatar' }) {
  const avatarUrl = figure?.avatar_url || ''
  const name = figure?.name || '灵偶'

  return (
    <div className={`figure-art figure-art--${mode}`} style={paletteStyle(figure?.figure_id || name)}>
      {avatarUrl ? (
        <img className="figure-art__image" src={avatarUrl} alt={name} />
      ) : (
        <div className="figure-art__fallback" aria-hidden="true">
          <span className="figure-art__portrait">
            <span className="figure-art__hair" />
            <span className="figure-art__head" />
            <span className="figure-art__neck" />
            <span className="figure-art__body" />
            <span className="figure-art__collar" />
          </span>
          <span className="figure-art__initial">{name.slice(0, 1)}</span>
        </div>
      )}
    </div>
  )
}

function FigureRosterCard({
  figure,
  active,
  onOpen,
  onSetActive,
  onEdit,
}: {
  figure: FigureProfile
  active: boolean
  onOpen: () => void
  onSetActive: () => void
  onEdit: () => void
}) {
  const archetype = getFigureArchetype(figure)
  const level = getFigureLevel(figure)
  const points = getFigurePoints(figure)
  const streak = getFigureStreak(figure)

  return (
    <article
      className={`mature-character-card ${active ? 'mature-character-card--active' : ''}`}
      onClick={onOpen}
      onKeyDown={event => {
        if (event.key === 'Enter') onOpen()
      }}
      role="button"
      tabIndex={0}
      style={paletteStyle(figure.figure_id)}
    >
      <div className="character-card__top">
        <span className="character-card__badge">{level}</span>
        {active && <span className="character-card__status">出战</span>}
      </div>

      <FigureArt figure={figure} />

      <div className="character-card__shade" />
      <div className="character-card__body">
        <div className="character-card__info-panel">
          <div className="character-card__title-row">
            <div className="min-w-0">
              <h3 className="character-card__name">{figure.name}</h3>
              <p className="character-card__archetype">{archetype}</p>
            </div>
            <span className="character-card__point-badge">{points}</span>
          </div>

          <div className="character-card__meta">
            <span>Affinity</span>
            <span>{Math.round(relationshipPercent(points))}%</span>
          </div>

          <div className="character-card__progress">
            <div
              className="character-card__progress-fill"
              style={{ width: `${relationshipPercent(points)}%` }}
            />
          </div>

          <div className="character-card__actions" onClick={event => event.stopPropagation()}>
            <button
              onClick={onOpen}
              className="character-card__action character-card__action--ghost"
            >
              详情
            </button>
            <button
              onClick={active ? onEdit : onSetActive}
              className="character-card__action character-card__action--primary"
            >
              {active ? '编辑' : '出战'}
            </button>
          </div>

          {streak > 0 && (
            <p className="character-card__streak">连续陪伴 {streak} 天</p>
          )}
        </div>
      </div>
    </article>
  )
}

export default function HomePage() {
  const navigate = useNavigate()
  const [baseData, setBaseData] = useState<any>(null)
  const [figures, setFigures] = useState<FigureProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [showUnbindModal, setShowUnbindModal] = useState(false)
  const [binding, setBinding] = useState(false)

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    setLoading(true)
    try {
      const base = await apiBases.get('BASE-001').catch(() => null)
      setBaseData(base)
      const figList = await apiFigures.list().catch(() => [])
      setFigures(figList)
    } catch {}
    setLoading(false)
  }

  async function handleSetActive(figureId: string) {
    try {
      await apiBases.setActiveFigure('BASE-001', figureId)
      loadData()
    } catch {}
  }

  async function handleUnbind() {
    setBinding(true)
    try {
      await apiBases.unbind({ base_id: 'BASE-001', user_id: 'user_default' })
      setShowUnbindModal(false)
      navigate('/bind')
    } catch {}
    setBinding(false)
  }

  const activeFigureId = baseData?.base?.active_figure_id
  const isBound = !!baseData?.base
  const activeFigure = baseData?.figure || figures.find(fig => fig.figure_id === activeFigureId)
  const activeArchetype = getFigureArchetype(activeFigure)
  const activeLevel = getFigureLevel(activeFigure)
  const activePoints = getFigurePoints(activeFigure)
  const activeStreak = getFigureStreak(activeFigure)

  if (loading) {
    return (
      <div className="min-h-screen bg-castle relative flex items-center justify-center overflow-hidden">
        <StarField count={18} />
        <div className="relative z-10 flex flex-col items-center gap-4">
          <div className="liquid-droplet flex h-16 w-16 items-center justify-center rounded-full text-2xl font-black text-purple-800">
            ✦
          </div>
          <p className="text-sm font-medium text-purple-500">灵魂舱启动中…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-castle relative overflow-hidden">
      <StarField count={18} />
      <div className="pointer-events-none absolute -top-32 left-1/2 h-80 w-80 -translate-x-1/2 rounded-full bg-white/66 blur-3xl" />
      <div className="pointer-events-none absolute top-20 -right-28 h-72 w-72 rounded-full bg-violet-200/28 blur-3xl" />
      <div className="pointer-events-none absolute bottom-16 -left-28 h-72 w-72 rounded-full bg-purple-200/20 blur-3xl" />

      <div className="relative z-10 mx-auto max-w-lg px-4 pb-28 pt-10">
        <header className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="liquid-droplet liquid-droplet--pill mb-2 inline-flex items-center gap-1.5 px-3 py-1 text-[10px] font-semibold tracking-[0.18em] text-purple-500">
              <span>✦</span>
              <span>LINGOU</span>
            </div>
            <h1 className="text-[30px] font-black leading-tight text-soul-gradient">灵偶 Crew</h1>
            <p className="mt-1 text-xs font-medium text-purple-400">选择今天陪你出战的灵魂伙伴</p>
          </div>

          <div className="shrink-0 text-right">
            <div className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-semibold shadow-sm ring-1 ${
              isBound
                ? 'bg-white/76 text-emerald-600 ring-emerald-100'
                : 'bg-white/70 text-purple-500 ring-purple-100'
            }`}>
              <span className={`h-2 w-2 rounded-full ${isBound ? 'bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.8)]' : 'bg-purple-300'}`} />
              {isBound ? baseData.base.base_id : '未绑定'}
            </div>
            <button
              onClick={() => isBound ? setShowUnbindModal(true) : navigate('/bind')}
              className="mt-2 block w-full rounded-full bg-white/50 px-3 py-1 text-[11px] font-medium text-purple-500 ring-1 ring-white/70 transition-colors hover:bg-white/80"
            >
              {isBound ? '解绑底座' : '去绑定'}
            </button>
          </div>
        </header>

        <section className="mb-4 overflow-hidden rounded-[34px] bg-[#130d24] p-[1px] shadow-[0_24px_70px_rgba(74,45,139,0.22)]">
          <div className="relative overflow-hidden rounded-[33px] bg-[radial-gradient(circle_at_22%_0%,rgba(168,85,247,0.45),transparent_34%),radial-gradient(circle_at_84%_20%,rgba(236,72,153,0.35),transparent_30%),linear-gradient(145deg,#181026_0%,#251448_56%,#120b20_100%)] px-4 pb-4 pt-4 text-white">
            <div className="absolute inset-0 opacity-35 [background-image:radial-gradient(circle_at_20%_20%,rgba(255,255,255,0.5)_0_1px,transparent_1px)] [background-size:18px_18px]" />
            <div className="relative flex items-center justify-between">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-white/44">Active Soul</p>
                <h2 className="mt-1 text-lg font-black">当前出战</h2>
              </div>
              <span className={`rounded-full px-2.5 py-1 text-[10px] font-black ${LEVEL_COLORS[activeLevel] || LEVEL_COLORS['陌生']}`}>
                {activeFigure ? activeLevel : '待唤醒'}
              </span>
            </div>

            {activeFigure ? (
              <div className="relative mt-3 grid grid-cols-[0.84fr_1.16fr] items-end gap-3">
                <div className="relative min-h-[158px]">
                  <FigureArt figure={activeFigure} mode="hero" />
                </div>
                <div className="relative pb-1">
                  <h3 className="truncate text-[26px] font-black leading-none">{activeFigure.name}</h3>
                  <p className="mt-2 line-clamp-2 text-sm font-medium leading-5 text-white/62">{activeArchetype}</p>
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    <MetricChip label="羁绊" value={activePoints} />
                    <MetricChip label="陪伴" value={`${activeStreak}天`} />
                    <MetricChip label="收藏" value={figures.length} />
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <button
                      onClick={() => navigate(`/soul/${activeFigure.figure_id}`)}
                      className="home-active-action home-active-action--ghost"
                    >
                      羁绊主页
                    </button>
                    <button
                      onClick={() => navigate('/dialogue-debug')}
                      className="home-active-action home-active-action--primary"
                    >
                      开始对话
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="relative mt-4 rounded-[28px] bg-white/10 p-5 text-center ring-1 ring-white/16 backdrop-blur-xl">
                <div className="mx-auto mb-3 flex h-20 w-20 items-center justify-center rounded-full bg-white/16 text-3xl font-black ring-1 ring-white/24">
                  灵
                </div>
                <p className="font-bold">还没有灵偶出战</p>
                <p className="mt-1 text-xs text-white/56">召唤一个灵魂，点亮你的收藏舱</p>
              </div>
            )}
          </div>
        </section>

        <section>
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h3 className="text-base font-black text-purple-950">灵偶列表</h3>
              <p className="text-[11px] font-medium text-purple-400">像角色卡一样管理你的灵魂队伍</p>
            </div>
            <span className="rounded-full bg-white/60 px-3 py-1 text-[11px] font-bold text-purple-500 ring-1 ring-white/70">
              {figures.length} Members
            </span>
          </div>

          {figures.length === 0 ? (
            <div className="glass-card mb-4 p-8 text-center">
              <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-3xl bg-white/30 text-2xl font-black text-purple-700 ring-1 ring-white/70">
                +
              </div>
              <p className="font-bold text-purple-900">还没有被唤醒的灵魂</p>
              <p className="mt-1 text-xs text-purple-400">从一只手办开始，创建你的第一位灵偶</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {figures.map(fig => (
                <FigureRosterCard
                  key={fig.figure_id}
                  figure={fig}
                  active={fig.figure_id === activeFigureId}
                  onOpen={() => navigate(`/soul/${fig.figure_id}`)}
                  onSetActive={() => handleSetActive(fig.figure_id)}
                  onEdit={() => navigate(`/soul/${fig.figure_id}/edit`)}
                />
              ))}
            </div>
          )}
        </section>

        <section className="mt-5 grid grid-cols-3 gap-2.5">
          {QUICK_ACTIONS.map(action => (
            <LiquidGlassPanel
              key={action.path}
              className="rounded-[24px]"
              contentClassName="h-full"
              radius={24}
              variant="control"
              interactive
            >
              <button onClick={() => navigate(action.path)} className="h-full w-full p-3 text-left">
                <div className="liquid-droplet liquid-droplet--icon mb-2 text-lg font-black">
                  <span>{action.icon}</span>
                </div>
                <p className="text-sm font-black text-purple-950">{action.title}</p>
                <p className="mt-0.5 text-[10px] font-semibold text-purple-400/90">{action.subtitle}</p>
              </button>
            </LiquidGlassPanel>
          ))}
        </section>
      </div>

      {showUnbindModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowUnbindModal(false)} />
          <div className="glass-card relative w-full max-w-sm animate-fade-in p-6">
            <div className="absolute -right-12 -top-12 h-32 w-32 rounded-full bg-violet-200/28 blur-2xl" />
            <div className="relative">
              <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-white/30 text-2xl ring-1 ring-white/70">
                ⛓
              </div>
              <h3 className="text-center text-lg font-black text-soul-gradient">确认解绑底座？</h3>
              <p className="mb-6 mt-3 text-center text-sm text-purple-600">
                解绑后，灵偶档案仍然保留。<br />
                <span className="text-purple-500">你可以随时重新扫码绑定。</span>
              </p>
              <div className="flex gap-3">
                <button
                  onClick={() => setShowUnbindModal(false)}
                  className="flex-1 rounded-2xl border border-white/70 bg-white/28 py-2.5 text-sm font-bold text-purple-700 backdrop-blur-xl"
                >
                  取消
                </button>
                <button
                  onClick={handleUnbind}
                  disabled={binding}
                  className="flex-1 rounded-2xl bg-red-500 py-2.5 text-sm font-bold text-white shadow-lg shadow-red-200/60 disabled:opacity-50"
                >
                  {binding ? '解绑中…' : '确认解绑'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
