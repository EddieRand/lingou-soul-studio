import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiBases, apiFigures, apiHardware, type BaseDetail, type EventResponse } from '../services/api'
import StarField from '../components/StarField'
import PageHeader from '../components/PageHeader'
import LiquidGlassPanel from '../components/LiquidGlassPanel'
import SoulFigureStage from '../components/SoulFigureStage'

const EVENT_TYPES = [
  { key: 'figure_placed', label: '放上底座', emoji: '🪑' },
  { key: 'light_touch', label: '轻 触', emoji: '👆' },
  { key: 'heavy_press', label: '重 按', emoji: '🤚' },
  { key: 'double_tap', label: '双 击', emoji: '👏' },
]

const LED_LABELS: Record<string, string> = {
  golden_flash: '✨ 金光闪烁',
  soft_glow: '💡 柔和光晕',
  red_flash: '🔴 红色警告',
  star_blink: '⭐ 星光闪烁',
}

const MOOD_LABELS: Record<string, string> = {
  happy: '开心',
  lonely: '孤独',
  attached: '依恋',
  annoyed: '烦躁',
  attention: '关注',
  sleepy: '困倦',
}

export default function HardwareSimPage() {
  const navigate = useNavigate()
  const [baseId, setBaseId] = useState<string | null>(null)
  const [baseData, setBaseData] = useState<BaseDetail | null>(null)
  const [figures, setFigures] = useState<any[]>([])
  const [activeResponse, setActiveResponse] = useState<EventResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    try {
      const bases = await apiBases.list()
      const currentBase = bases[0] || null
      setBaseData(currentBase)
      setBaseId(currentBase?.base.base_id || null)
      if (!currentBase) {
        setFigures([])
        return
      }
      const figList = await apiFigures.list()
      setFigures(figList)
    } catch {
      setBaseId(null)
      setBaseData(null)
      setFigures([])
    }
  }

  async function handleSimulate(eventType: string) {
    if (!baseId) return
    setLoading(true)
    setError('')
    setActiveResponse(null)
    try {
      const resp = await apiHardware.simulate(baseId, eventType)
      setActiveResponse(resp)
      loadData()
    } catch (e: any) {
      setError(e.message || '模拟失败')
    } finally {
      setLoading(false)
    }
  }

  const moodEntries = activeResponse
    ? Object.entries(activeResponse.mood).filter(([k]) => k !== 'last_dialogue_at')
    : []

  return (
    <div className="min-h-screen bg-castle relative overflow-hidden">
      <StarField count={18} />
      <div className="pointer-events-none absolute -top-24 left-1/2 h-72 w-72 -translate-x-1/2 rounded-full bg-white/62 blur-3xl" />
      
      <PageHeader
        title="互动控制台"
        subtitle={baseId ? `底座 ${baseId} · 触摸事件模拟` : '尚未绑定底座'}
        onBack={() => navigate('/home')}
      />

      <div className="relative z-10 mx-auto max-w-lg px-4 pb-28">

        {/* 无灵偶空态引导 */}
        {!baseData?.figure && (
          <div className="glass-card mb-4 p-6 text-center">
            <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-3xl bg-white/30 text-3xl ring-1 ring-white/70">
              ✦
            </div>
            <p className="mb-2 font-bold text-purple-900">还没有设置当前灵偶</p>
            <p className="mb-4 text-xs text-purple-400">请先在「我的灵偶」选择一个灵偶</p>
            <button
              onClick={() => navigate('/home')}
              className="rounded-full bg-gradient-to-r from-purple-500 to-pink-500 px-4 py-2 text-sm font-bold text-white shadow-lg shadow-purple-300/40"
            >
              去我的灵偶选择
            </button>
          </div>
        )}

        {/* Active Figure Info */}
        <LiquidGlassPanel
          className="mb-4"
          contentClassName="liquid-brand-surface p-4 text-white"
          radius={30}
          variant="hero"
        >
            <div className="mb-3 flex items-center justify-between">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-white/60">Active Device</p>
                <p className="mt-1 text-sm font-semibold text-white/80">当前互动对象</p>
              </div>
              <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${
                baseData?.figure ? 'bg-emerald-300 text-emerald-950' : 'bg-white/20 text-white/70'
              }`}>
                {baseData?.figure ? 'READY' : 'EMPTY'}
              </span>
            </div>
          {baseData?.figure ? (
              <div className="soul-presence-card">
                <div className="soul-presence-card__stage">
                  <div className="soul-presence-card__glow" />
                  <SoulFigureStage figure={baseData.figure} className="soul-presence-card__figure" />
                  <div className="soul-presence-card__shine" />
                </div>
                <div className="soul-presence-card__content">
                  <p className="truncate text-2xl font-black">{baseData.figure.name}</p>
                  <p className="mt-1 text-xs text-white/70">
                {baseData.figure.soul_profile?.archetype} · 交互 {baseData.figure.memory?.interaction_count || 0} 次
              </p>
                  <button
                    onClick={() => {
                      const figureId = baseData.figure?.figure_id
                      if (figureId) navigate(`/soul/${figureId}`)
                    }}
                    className="mt-3 rounded-full bg-white px-4 py-2 text-xs font-black text-purple-950 shadow-lg shadow-black/15"
                  >
                    羁绊主页
                  </button>
                </div>
            </div>
          ) : (
              <p className="text-sm text-white/70">未放置灵偶</p>
          )}
        </LiquidGlassPanel>

        {/* 4 Touch Buttons */}
        <section className="hardware-event-panel mb-4">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <p className="text-sm font-black text-purple-950">触摸事件</p>
              <p className="text-[11px] font-semibold text-purple-400">模拟底座输入，查看灵偶即时反馈</p>
            </div>
            <span className="rounded-full bg-white/70 px-2.5 py-1 text-[10px] font-black text-purple-500 ring-1 ring-white/80">
              {loading ? 'RUNNING' : 'READY'}
            </span>
          </div>
          <div className="grid grid-cols-4 gap-2">
          {EVENT_TYPES.map(evt => (
            <button
              key={evt.key}
              onClick={() => handleSimulate(evt.key)}
              disabled={loading || !baseData?.figure}
              className={`hardware-event-button ${!baseData?.figure ? 'hardware-event-button--disabled' : ''}`}
            >
              <span className="hardware-event-button__icon">{evt.emoji}</span>
              <span>{evt.label.replace(/\s/g, '')}</span>
            </button>
          ))}
          </div>
        </section>

        {error && (
          <div className="mb-4 rounded-2xl bg-red-50 p-3 text-center text-sm font-medium text-red-600">
            {error}
          </div>
        )}

        {/* Response Display */}
        {activeResponse && (
          <section className="glass-card mb-4 space-y-4 p-4">
            <div>
              <p className="mb-1 text-[10px] font-bold uppercase tracking-[0.2em] text-purple-400">Response</p>
              <p className="text-lg font-bold leading-relaxed text-purple-950">
                「{activeResponse.reply}」
              </p>
            </div>

            {activeResponse.led_effect && (
              <div className="flex items-center justify-between rounded-2xl bg-white/60 px-3 py-2 ring-1 ring-white/70">
                <p className="text-xs font-bold text-purple-500">灯效</p>
                <span className="text-sm font-semibold text-purple-700">
                  {LED_LABELS[activeResponse.led_effect] || activeResponse.led_effect}
                </span>
              </div>
            )}

            <div>
              <p className="mb-2 text-xs font-bold text-purple-500">情绪状态</p>
              <div className="grid grid-cols-3 gap-2">
                {moodEntries.map(([key, value]) => (
                  <div key={key} className="rounded-2xl bg-white/65 px-3 py-2 ring-1 ring-white/70">
                    <p className="text-xs text-purple-400">{MOOD_LABELS[key] || key}</p>
                    <p className="text-base font-black text-purple-700">{value as number}</p>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {/* Figure list quick switch */}
        {figures.length > 0 && (
          <section className="glass-card p-4">
            <p className="mb-3 text-sm font-black text-purple-900">灵偶列表（点击切换）</p>
            <div className="flex flex-wrap gap-2">
              {figures.map(fig => (
                <button
                  key={fig.figure_id}
                  onClick={async () => {
                    if (!baseId) return
                    setError('')
                    try {
                      await apiBases.setActiveFigure(baseId, fig.figure_id)
                      loadData()
                    } catch (error) {
                      setError(error instanceof Error ? error.message : '切换灵偶失败，请重试')
                    }
                  }}
                  className={`soul-switch-chip ${
                    baseData?.figure?.figure_id === fig.figure_id
                      ? 'soul-switch-chip--active'
                      : 'soul-switch-chip--idle'
                  }`}
                >
                  <span className="soul-switch-chip__avatar">
                    {fig.avatar_url ? <img src={fig.avatar_url} alt="" /> : <span>{fig.name.slice(0, 1)}</span>}
                  </span>
                  <span>{fig.name}</span>
                </button>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
