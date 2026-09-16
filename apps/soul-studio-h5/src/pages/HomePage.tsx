import { useEffect, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'

import StarField from '../components/StarField'
import { useAuth } from '../context/AuthContext'
import {
  apiBases,
  apiFigures,
  apiMemories,
  type BaseDetail,
  type FigureProfile,
  type MemoryCollection,
} from '../services/api'
import { conversationPath, resolvePrimaryFlow } from '../services/primaryFlow'

const FIGURE_PALETTES = [
  ['#7c3aed', '#ec4899', '#f8a4d8'],
  ['#5b5ff5', '#a855f7', '#d8c4ff'],
  ['#db2777', '#fb7185', '#ffd1e7'],
  ['#4338ca', '#06b6d4', '#c4f1ff'],
]

function paletteStyle(seed: string): CSSProperties {
  const code = seed.split('').reduce((sum, char) => sum + char.charCodeAt(0), 0)
  const palette = FIGURE_PALETTES[code % FIGURE_PALETTES.length]
  return {
    '--figure-a': palette[0],
    '--figure-b': palette[1],
    '--figure-c': palette[2],
  } as CSSProperties
}

function FigureArt({ figure }: { figure: FigureProfile }) {
  return (
    <div className="figure-art figure-art--hero" style={paletteStyle(figure.figure_id)}>
      {figure.avatar_url ? (
        <img className="figure-art__image" src={figure.avatar_url} alt={figure.name} />
      ) : (
        <div className="figure-art__fallback" aria-hidden="true">
          <span className="figure-art__portrait">
            <span className="figure-art__hair" />
            <span className="figure-art__head" />
            <span className="figure-art__neck" />
            <span className="figure-art__body" />
            <span className="figure-art__collar" />
          </span>
          <span className="figure-art__initial">{figure.name.slice(0, 1)}</span>
        </div>
      )}
    </div>
  )
}

export default function HomePage() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const [baseData, setBaseData] = useState<BaseDetail | null>(null)
  const [figure, setFigure] = useState<FigureProfile | null>(null)
  const [memories, setMemories] = useState<MemoryCollection | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false

    async function loadPrimaryFlow() {
      setLoading(true)
      setError('')
      try {
        const bases = await apiBases.list()
        if (cancelled) return
        const currentBase = bases[0]
        if (!currentBase) {
          navigate('/bind', { replace: true })
          return
        }
        const figures = currentBase.figure ? [] : await apiFigures.list()
        if (cancelled) return
        const decision = resolvePrimaryFlow(bases, figures)
        if (decision.action === 'bind') {
          navigate('/bind', { replace: true })
          return
        }
        if (decision.action === 'create') {
          navigate('/create', { replace: true })
          return
        }

        let readyBase = decision.base
        let readyFigure = decision.figure
        if (decision.action === 'activate') {
          readyBase = await apiBases.setActiveFigure(
            decision.base.base.base_id,
            decision.figure.figure_id,
          )
          readyFigure = readyBase.figure || decision.figure
        }
        if (cancelled) return
        setBaseData(readyBase)
        setFigure(readyFigure)
        setMemories(
          await apiMemories.list(readyFigure.figure_id).catch(() => null),
        )
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : '加载失败，请重试')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void loadPrimaryFlow()
    return () => {
      cancelled = true
    }
  }, [navigate])

  if (loading) {
    return (
      <main className="flex min-h-[100svh] items-center justify-center bg-castle">
        <p className="text-sm font-semibold text-purple-500">正在恢复当前灵偶…</p>
      </main>
    )
  }

  if (error || !baseData || !figure) {
    return (
      <main className="flex min-h-[100svh] flex-col items-center justify-center gap-4 bg-castle px-6 text-center">
        <p role="alert" className="text-sm font-semibold text-red-600">
          {error || '当前灵偶尚未就绪'}
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded-2xl bg-purple-600 px-5 py-3 text-sm font-bold text-white"
        >
          重新加载
        </button>
      </main>
    )
  }

  const confirmedFacts = memories?.confirmed_facts || []
  const latestFact = confirmedFacts[confirmedFacts.length - 1]?.content
  const oneLine = figure.soul_profile?.one_line
    || figure.soul_profile?.character_profile?.one_line
    || '随时可以继续上次的话题'

  return (
    <main className="relative min-h-[100svh] overflow-hidden bg-castle">
      <StarField count={14} />
      <div className="relative z-10 mx-auto max-w-lg px-4 pb-32 pt-8">
        <header className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] font-bold tracking-[0.2em] text-purple-400">LINGOU</p>
            <h1 className="mt-1 text-2xl font-black text-purple-950">当前灵偶</h1>
          </div>
          <div className="flex items-center gap-2">
            <span className="max-w-24 truncate text-xs font-semibold text-purple-500">
              {user?.username}
            </span>
            <button
              type="button"
              onClick={() => navigate('/bind')}
              className="rounded-full bg-white/70 px-3 py-2 text-xs font-bold text-purple-600 ring-1 ring-white/80"
            >
              设备
            </button>
            <button
              type="button"
              onClick={logout}
              className="rounded-full bg-white/50 px-3 py-2 text-xs font-bold text-purple-400 ring-1 ring-white/70"
            >
              退出
            </button>
          </div>
        </header>

        <section className="mt-5 overflow-hidden rounded-[30px] bg-[#180f2d] p-4 text-white shadow-[0_24px_70px_rgba(74,45,139,0.25)]">
          <div className="grid grid-cols-[0.88fr_1.12fr] items-end gap-4">
            <div className="relative min-h-[190px] overflow-hidden rounded-[24px]">
              <FigureArt figure={figure} />
            </div>
            <div className="pb-2">
              <p className="text-[10px] font-bold tracking-[0.18em] text-purple-200">
                {figure.soul_profile?.archetype || '陪伴型'}
              </p>
              <h2 className="mt-2 truncate text-3xl font-black">{figure.name}</h2>
              <p className="mt-3 line-clamp-3 text-sm leading-6 text-white/70">{oneLine}</p>
              <button
                type="button"
                onClick={() => navigate(conversationPath(figure.figure_id))}
                className="mt-5 w-full rounded-2xl bg-white py-3 text-sm font-black text-purple-950"
              >
                继续交流
              </button>
            </div>
          </div>
        </section>

        <section className="glass-card mt-4 p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-[10px] font-bold tracking-[0.16em] text-purple-400">共同记忆</p>
              <p className="mt-2 text-base font-bold leading-6 text-purple-950">
                {latestFact || '还没有确认的共同记忆'}
              </p>
            </div>
            <span className="shrink-0 rounded-full bg-purple-100 px-2.5 py-1 text-xs font-black text-purple-600">
              {memories?.confirmed_facts.length || 0}/10
            </span>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => navigate(`/soul/${figure.figure_id}`)}
              className="rounded-2xl bg-purple-100 py-3 text-sm font-bold text-purple-700"
            >
              管理记忆
            </button>
            <button
              type="button"
              onClick={() => navigate(`/soul/${figure.figure_id}/edit`)}
              className="rounded-2xl bg-white/70 py-3 text-sm font-bold text-purple-600 ring-1 ring-purple-100"
            >
              编辑档案
            </button>
          </div>
        </section>

        <p className="mt-4 text-center text-[11px] font-semibold text-purple-300">
          已连接底座 {baseData.base.base_id}
        </p>
      </div>
    </main>
  )
}
