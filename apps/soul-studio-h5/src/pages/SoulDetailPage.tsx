import { useState, useEffect, type CSSProperties } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { apiFigures, apiEvents, type FigureProfile } from '../services/api'
import StarField from '../components/StarField'
import PageHeader from '../components/PageHeader'
import LiquidGlassPanel from '../components/LiquidGlassPanel'

const MOOD_EMOJI: Record<string, { emoji: string; filter: string; desc: string }> = {
  happy: { emoji: '愉', filter: 'brightness(1.16) saturate(1.18)', desc: '开心' },
  lonely: { emoji: '念', filter: 'brightness(0.88) saturate(0.84)', desc: '想念' },
  sleepy: { emoji: '眠', filter: 'brightness(0.9) saturate(0.8)', desc: '困倦' },
  annoyed: { emoji: '傲', filter: 'brightness(0.94) saturate(0.9)', desc: '烦躁' },
  attached: { emoji: '恋', filter: 'brightness(1.1) saturate(1.12)', desc: '依恋' },
}

const LEVELS = ['陌生', '熟悉', '依赖', '羁绊']
const LEVEL_THRESHOLDS = { '陌生': 0, '熟悉': 21, '依赖': 61, '羁绊': 151 }
const LEVEL_NEXT = { '陌生': '熟悉', '熟悉': '依赖', '依赖': '羁绊', '羁绊': null }

const LEVEL_UNLOCKS = {
  '陌生': { '亲密昵称': false, '掏心台词': false, '专属话题': false },
  '熟悉': { '亲密昵称': false, '掏心台词': false, '专属话题': true },
  '依赖': { '亲密昵称': true, '掏心台词': false, '专属话题': true },
  '羁绊': { '亲密昵称': true, '掏心台词': true, '专属话题': true },
}

const DEFAULT_GREETINGS: Record<string, string> = {
  '御姐照顾型': '累了吗？我在。',
  '傲娇吐槽型': '哼，终于舍得来找我了？',
  '软萌治愈型': '见到你真开心~抱抱！',
  '元气伙伴型': '冲！今天也要元气满满！',
  '冷淡守护型': '……回来了。',
  '桀骜战神型': '俺老孙等你半天了。',
  '搞怪捣蛋型': '嘿嘿！想我了吗？',
  '憨憨吃货型': '有吃的吗？我饿了！',
  '机械副官型': '系统检测到用户回归。',
  '萌宠陪伴型': '汪汪！主人回来了！',
  '潮玩幸运型': '好运来~见到你真开心！',
}

const EMOTION_KEYS = ['happy', 'lonely', 'attached', 'annoyed', 'attention', 'sleepy'] as const

const FIGURE_PALETTES = [
  ['#7c3aed', '#ec4899', '#f8a4d8'],
  ['#5b5ff5', '#a855f7', '#d8c4ff'],
  ['#db2777', '#fb7185', '#ffd1e7'],
  ['#4338ca', '#06b6d4', '#c4f1ff'],
  ['#6d28d9', '#f59e0b', '#ffe1a8'],
]

interface DialogueLog {
  figure_id: string
  user_input_text: string
  reply_text: string
  created_at: string
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

function relationshipPercent(points: number) {
  return Math.min(100, Math.max(8, (points / 151) * 100))
}

function levelIndex(level: string) {
  return Math.max(0, LEVELS.indexOf(level)) + 1
}

function FigureStageArt({ figure, moodFilter }: { figure: FigureProfile; moodFilter: string }) {
  const avatarUrl = figure.avatar_url || ''

  return (
    <div className="profile-figure-art" style={paletteStyle(figure.figure_id)}>
      {avatarUrl ? (
        <img className="profile-figure-art__image" src={avatarUrl} alt={figure.name} style={{ filter: moodFilter }} />
      ) : (
        <div className="profile-figure-art__fallback" style={{ filter: moodFilter }} aria-hidden="true">
          <span className="profile-figure-art__portrait">
            <span className="profile-figure-art__hair" />
            <span className="profile-figure-art__head" />
            <span className="profile-figure-art__neck" />
            <span className="profile-figure-art__body" />
            <span className="profile-figure-art__collar" />
          </span>
          <span className="profile-figure-art__name">{figure.name.slice(0, 1)}</span>
        </div>
      )}
    </div>
  )
}

function SectionTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-3 flex items-end justify-between gap-3">
      <div>
        <h3 className="text-base font-black text-purple-950">{title}</h3>
        {subtitle && <p className="mt-0.5 text-[11px] font-semibold text-purple-400">{subtitle}</p>}
      </div>
    </div>
  )
}

export default function SoulDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [figure, setFigure] = useState<FigureProfile | null>(null)
  const [dialogueLogs, setDialogueLogs] = useState<DialogueLog[]>([])
  const [eventLogs, setEventLogs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [simulating, setSimulating] = useState(false)
  const [simulateHours, setSimulateHours] = useState<number>(72)
  const [showDebugPanel, setShowDebugPanel] = useState(false)

  const [boostingRelationship, setBoostingRelationship] = useState(false)
  const [boostLevel, setBoostLevel] = useState<string>('羁绊')
  const [boostStreak, setBoostStreak] = useState<number>(7)

  const [capsulePage, setCapsulePage] = useState(1)
  const [dialoguePage, setDialoguePage] = useState(1)
  const [eventPage, setEventPage] = useState(1)
  const PAGE_SIZE = 5

  useEffect(() => {
    if (!id) return
    const figureId: string = id
    async function loadData() {
      setLoading(true)
      try {
        const fig = await apiFigures.get(figureId)
        setFigure(fig)
        try {
          const dlogs = await fetch(`/api/dialogue/logs?figure_id=${figureId}&limit=10`)
            .then(r => r.json())
            .catch(() => [])
          setDialogueLogs(dlogs)
        } catch {}
        try {
          const elogs = await apiEvents.getLogs({ figure_id: figureId, limit: 10 })
          setEventLogs(elogs)
        } catch {}
      } catch (e: any) {
        setError(e.message || '加载失败')
      }
      setLoading(false)
    }
    loadData()
  }, [id])

  async function handleSimulateAbsence() {
    if (!id) return
    setSimulating(true)
    try {
      const updatedFigure = await apiFigures.simulateAbsence(id, simulateHours)
      setFigure(updatedFigure)
      try {
        const elogs = await apiEvents.getLogs({ figure_id: id, limit: 10 })
        setEventLogs(elogs)
      } catch {}
    } catch (e: any) {
      setError(e.message || '模拟失败')
    }
    setSimulating(false)
  }

  async function handleBoostRelationship() {
    if (!id) return
    setBoostingRelationship(true)
    try {
      const updatedFigure = await apiFigures.boostRelationship(id, { level: boostLevel, streak_days: boostStreak })
      setFigure(updatedFigure)
    } catch (e: any) {
      setError(e.message || '快进关系失败')
    }
    setBoostingRelationship(false)
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-castle flex items-center justify-center">
        <p className="text-purple-400">加载中…</p>
      </div>
    )
  }

  if (error || !figure) {
    return (
      <div className="min-h-screen bg-castle flex flex-col items-center justify-center">
        <StarField count={10} />
        <p className="text-purple-400 mb-4">{error || '灵偶不存在'}</p>
        <button
          onClick={() => navigate('/home')}
          className="px-4 py-2 bg-gradient-to-r from-purple-500 to-pink-500 text-white text-sm rounded-full font-medium"
        >
          去我的灵偶选择
        </button>
      </div>
    )
  }

  const archetype = figure.soul_profile?.archetype || '灵偶'
  const mood = figure.soul_profile?.emotion_state || {}
  const dominantMood = EMOTION_KEYS.reduce<typeof EMOTION_KEYS[number]>(
    (prev, curr) => (mood[curr] || 0) > (mood[prev] || 0) ? curr : prev,
    'happy',
  )
  const moodInfo = MOOD_EMOJI[dominantMood] || MOOD_EMOJI.happy
  const currentStatus = figure.life_status?.status_description || '正在等待你的呼唤…'
  const greeting = figure.soul_profile?.persona?.greeting || DEFAULT_GREETINGS[archetype] || '你好呀~'
  const relationshipLevel = (figure.memory?.relationship_level || '陌生') as '陌生' | '熟悉' | '依赖' | '羁绊'
  const relationshipPoints = figure.memory?.relationship_points || 0
  const nextLevel = LEVEL_NEXT[relationshipLevel]
  const nextThreshold = nextLevel ? LEVEL_THRESHOLDS[nextLevel as keyof typeof LEVEL_THRESHOLDS] : null
  const pointsToNext = nextThreshold ? Math.max(0, nextThreshold - relationshipPoints) : 0
  const streakDays = figure.memory?.streak_days || 0
  const capsules = figure.memory?.memory_capsule || []
  const currentUnlocks = LEVEL_UNLOCKS[relationshipLevel] || {}
  const lastInteraction = figure.memory?.last_interaction_at
    ? new Date(figure.memory.last_interaction_at).toLocaleDateString('zh-CN')
    : '暂无'

  return (
    <div className="min-h-screen bg-castle relative overflow-hidden">
      <StarField count={16} />
      <div className="pointer-events-none absolute -top-28 left-1/2 h-80 w-80 -translate-x-1/2 rounded-full bg-white/62 blur-3xl" />
      <div className="pointer-events-none absolute top-44 -right-24 h-72 w-72 rounded-full bg-fuchsia-200/20 blur-3xl" />

      <PageHeader
        title="羁绊主页"
        subtitle={figure.name}
        onBack={() => navigate('/home')}
        extra={
          <button
            onClick={() => navigate(`/soul/${figure.figure_id}/edit`)}
            className="rounded-full bg-white/70 px-3 py-1 text-xs font-bold text-purple-600 shadow-sm ring-1 ring-white/80 hover:bg-white/90"
          >
            编辑
          </button>
        }
      />

      <div className="relative z-10 mx-auto max-w-lg space-y-4 px-4 pb-28">
        <section className="profile-hero-card" style={paletteStyle(figure.figure_id)}>
          <div className="profile-hero-card__chrome" />
          <div className="relative z-10 flex items-start justify-between">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-white/80 drop-shadow-sm">灵偶档案</p>
              <h2 className="mt-1 text-3xl font-black leading-none text-white">{figure.name}</h2>
              <p className="mt-2 text-sm font-bold text-white/90 drop-shadow-sm">{archetype}</p>
            </div>
            <div className="rounded-2xl bg-white/20 px-3 py-2 text-right shadow-lg shadow-black/10 ring-1 ring-white/40 backdrop-blur-xl">
              <p className="text-[10px] font-bold text-white/80">心情</p>
              <p className="text-lg font-black text-white">{moodInfo.desc}</p>
            </div>
          </div>

          <div className="relative z-10 mt-4 min-h-[282px] overflow-hidden rounded-[30px] bg-black/14 ring-1 ring-white/14">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_45%_20%,rgba(255,255,255,0.22),transparent_24%),radial-gradient(circle_at_50%_55%,rgba(236,72,153,0.34),transparent_36%)]" />
            <div className="absolute inset-0 opacity-45 [background-image:radial-gradient(circle_at_center,rgba(255,255,255,0.68)_0_1px,transparent_1.8px)] [background-size:22px_22px]" />
            <FigureStageArt figure={figure} moodFilter={moodInfo.filter} />
            <div className="absolute left-3 right-3 bottom-3 z-20 rounded-[24px] bg-white/82 p-3 shadow-lg shadow-black/10 ring-1 ring-white/70 backdrop-blur-2xl">
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-purple-500">灵魂回应</p>
              <p className="mt-1 line-clamp-2 text-base font-bold leading-6 text-purple-950">"{greeting}"</p>
            </div>
          </div>

          <div className="relative z-10 mt-3 grid grid-cols-3 gap-2">
            <button
              onClick={() => navigate('/dialogue-debug')}
              className="rounded-full bg-white px-3 py-2.5 text-xs font-black text-purple-950 shadow-lg shadow-black/15"
            >
              对话
            </button>
            <button
              onClick={() => navigate('/simulate')}
              className="rounded-full bg-white/20 px-3 py-2.5 text-xs font-black text-white shadow-sm shadow-black/10 ring-1 ring-white/40 backdrop-blur-xl"
            >
              互动
            </button>
            <button
              onClick={() => navigate(`/soul/${figure.figure_id}/edit`)}
              className="rounded-full bg-white/20 px-3 py-2.5 text-xs font-black text-white shadow-sm shadow-black/10 ring-1 ring-white/40 backdrop-blur-xl"
            >
              装备
            </button>
          </div>
        </section>

        {figure.life_status && (
          <div className="rounded-[24px] bg-white/58 px-4 py-3 text-center text-sm font-semibold text-purple-600 shadow-sm ring-1 ring-white/72 backdrop-blur-xl">
            {currentStatus}
          </div>
        )}

        <LiquidGlassPanel className="bond-panel-shell" contentClassName="bond-panel" radius={30} variant="hero">
          <div className="bond-panel__aurora" />
          <div className="bond-panel__header">
            <div className="bond-panel__level-mark">
              <span>Lv.{levelIndex(relationshipLevel)}</span>
            </div>
            <div className="bond-panel__heading">
              <p className="bond-panel__eyebrow">羁绊等级</p>
              <h3>{relationshipLevel}</h3>
              <p>{nextLevel ? `距离 ${nextLevel} 还差 ${pointsToNext} 点` : '已达最高羁绊'}</p>
            </div>
            <div className="bond-panel__points">
              <strong>{relationshipPoints}</strong>
              <span>点</span>
            </div>
          </div>

          <div className="bond-panel__energy">
            <div className="bond-panel__energy-rail">
              <div
                className="bond-panel__energy-fill"
                style={{ width: `${relationshipPercent(relationshipPoints)}%` }}
              />
              <div className="bond-panel__energy-nodes">
                {LEVELS.map(level => (
                  <span
                    key={level}
                    className={relationshipPoints >= LEVEL_THRESHOLDS[level as keyof typeof LEVEL_THRESHOLDS] ? 'is-active' : ''}
                  />
                ))}
              </div>
            </div>
            <div className="bond-panel__level-row">
              {LEVELS.map(level => (
                <span
                  key={level}
                  className={relationshipPoints >= LEVEL_THRESHOLDS[level as keyof typeof LEVEL_THRESHOLDS] ? 'is-active' : ''}
                >
                  {level}
                </span>
              ))}
            </div>
            <div className="bond-panel__energy-meta">
              <span>羁绊能量</span>
              <strong>{Math.round(relationshipPercent(relationshipPoints))}%</strong>
            </div>
          </div>

          <div className="bond-panel__metrics">
            <div className="bond-panel__metric bond-panel__metric--warm">
              <span>连续陪伴</span>
              <strong>{streakDays}</strong>
              <small>天</small>
            </div>
            <div className="bond-panel__metric bond-panel__metric--violet">
              <span>交互次数</span>
              <strong>{figure.memory?.interaction_count || 0}</strong>
              <small>次</small>
            </div>
            <div className="bond-panel__metric bond-panel__metric--cool">
              <span>最近交互</span>
              <strong>{lastInteraction}</strong>
              <small>最近</small>
            </div>
          </div>

          <div className="bond-panel__unlock-row">
            {Object.entries(currentUnlocks).map(([key, unlocked]) => (
              <span
                key={key}
                className={`bond-panel__unlock ${unlocked ? 'is-unlocked' : 'is-locked'}`}
              >
                <span className="bond-panel__unlock-dot">{unlocked ? '解' : '锁'}</span>
                <span>{key}</span>
              </span>
            ))}
          </div>
        </LiquidGlassPanel>

        <section className="glass-card p-4">
          <SectionTitle title="羁绊日记" subtitle="记住你们相处过的瞬间" />
          {capsules.length === 0 ? (
            <p className="rounded-[22px] bg-white/44 py-6 text-center text-sm font-medium text-purple-400 ring-1 ring-white/68">
              还没有记录，继续培养你们的羁绊吧
            </p>
          ) : (
            <>
              <div className="space-y-2">
                {[...capsules].reverse().slice(0, capsulePage * PAGE_SIZE).map((cap: any, index: number) => (
                  <div key={index} className="memory-snippet">
                    <div className="memory-snippet__icon">
                      {cap.type === 'first_meet' ? '初' : cap.type === 'milestone' ? '星' : '记'}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <span className="text-xs font-bold text-purple-500">
                          {cap.type === 'first_meet' ? '初次相遇' : cap.type === 'milestone' ? '里程碑' : 'TA 记得'}
                        </span>
                        <span className="shrink-0 text-[10px] font-semibold text-purple-300">
                          {new Date(cap.created_at).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })}
                        </span>
                      </div>
                      <p className="text-sm leading-5 text-purple-900">{cap.content}</p>
                    </div>
                  </div>
                ))}
              </div>
              {capsules.length > PAGE_SIZE && (
                <button
                  onClick={() => setCapsulePage(capsulePage > 1 ? 1 : Math.ceil(capsules.length / PAGE_SIZE))}
                  className="mt-3 w-full rounded-full bg-white/44 py-2 text-xs font-bold text-purple-500 ring-1 ring-white/68 hover:bg-white/60 transition-colors"
                >
                  {capsulePage > 1 ? '收起' : `加载更多（${capsules.length - PAGE_SIZE} 条）`}
                </button>
              )}
            </>
          )}
        </section>

        <div className="grid grid-cols-2 gap-3">
          {figure.wake_names && figure.wake_names.length > 0 && (
            <div className="glass-card p-4">
              <SectionTitle title="唤醒词" />
              <div className="flex flex-wrap gap-2">
                {figure.wake_names.map((name, index) => (
                  <span key={index} className="rounded-full bg-purple-100/80 px-3 py-1.5 text-xs font-bold text-purple-600 ring-1 ring-purple-100">
                    {name}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="glass-card p-4">
            <SectionTitle title="音色" />
            <div className="space-y-3 text-sm">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-purple-300">能力</p>
                <p className="mt-1 truncate font-black text-purple-900">{figure.voice_profile?.tts_engine ? '云端情感声线' : '待配置'}</p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-purple-300">声线</p>
                <p className="mt-1 truncate font-black text-purple-900">{figure.voice_profile?.speaker ? '已绑定专属声线' : '未选择'}</p>
              </div>
            </div>
          </div>
        </div>

        <section className="glass-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <SectionTitle title="高级工具" subtitle="模拟重逢与状态变化" />
            <button
              onClick={() => setShowDebugPanel(!showDebugPanel)}
              className="rounded-full bg-white/58 px-3 py-1 text-xs font-bold text-purple-500 ring-1 ring-white/70"
            >
              {showDebugPanel ? '收起' : '展开'}
            </button>
          </div>

          {showDebugPanel && (
            <div className="space-y-3">
              <p className="text-xs text-purple-400">模拟离开时长，测试重逢反应</p>
              <div className="grid grid-cols-4 gap-2">
                {[1, 12, 72, 168].map(hours => (
                  <button
                    key={hours}
                    onClick={() => setSimulateHours(hours)}
                    className={`rounded-2xl px-3 py-2 text-xs font-bold transition-all ${
                      simulateHours === hours
                        ? 'bg-purple-500 text-white shadow-lg shadow-purple-200/60'
                        : 'bg-white/56 text-purple-600 ring-1 ring-white/70'
                    }`}
                  >
                    {hours < 24 ? `${hours}h` : `${hours / 24}天`}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="number"
                  value={simulateHours}
                  onChange={event => setSimulateHours(Number(event.target.value))}
                  className="w-24 rounded-2xl border border-white/72 bg-white/58 px-3 py-2 text-sm text-purple-900 focus:outline-none focus:ring-2 focus:ring-purple-300"
                  min={0}
                  max={720}
                />
                <span className="text-xs text-purple-500">小时</span>
              </div>

              <button
                onClick={handleSimulateAbsence}
                disabled={simulating}
                className="btn-soul w-full py-3 text-sm disabled:opacity-50"
              >
                {simulating ? '模拟中…' : '模拟离开'}
              </button>

              {figure.life_status && (
                <div className="rounded-2xl bg-white/56 p-3 text-xs text-purple-600 ring-1 ring-white/70">
                  <p>冷落等级: <span className="font-bold">{figure.life_status.neglect_tier}</span></p>
                  <p>离开时长: <span className="font-bold">{Math.round(figure.life_status.elapsed_hours)}小时</span></p>
                  <p className="mt-1">{figure.life_status.status_description}</p>
                </div>
              )}

              <div className="border-t border-purple-100/60 pt-3">
                <p className="mb-2 text-xs font-bold text-purple-500">快进关系</p>
                <div className="mb-2 grid grid-cols-4 gap-2">
                  {LEVELS.map(level => (
                    <button
                      key={level}
                      onClick={() => setBoostLevel(level)}
                      className={`rounded-2xl px-2 py-2 text-xs font-bold transition-all ${
                        boostLevel === level
                          ? 'bg-gradient-to-r from-purple-500 to-pink-500 text-white'
                          : 'bg-white/56 text-purple-600 ring-1 ring-white/70'
                      }`}
                    >
                      {level}
                    </button>
                  ))}
                </div>
                <div className="mb-2 flex items-center gap-2">
                  <span className="text-xs text-purple-500">连续陪伴</span>
                  <input
                    type="number"
                    value={boostStreak}
                    onChange={event => setBoostStreak(Number(event.target.value))}
                    className="w-20 rounded-2xl border border-white/72 bg-white/58 px-3 py-2 text-sm text-purple-900 focus:outline-none focus:ring-2 focus:ring-purple-300"
                    min={0}
                    max={365}
                  />
                  <span className="text-xs text-purple-500">天</span>
                </div>
                <button
                  onClick={handleBoostRelationship}
                  disabled={boostingRelationship}
                  className="w-full rounded-2xl bg-gradient-to-r from-pink-500 to-purple-500 py-3 text-sm font-bold text-white shadow-lg shadow-purple-200/60 transition-opacity disabled:opacity-50"
                >
                  {boostingRelationship ? '快进中…' : `快进到 ${boostLevel} + ${boostStreak}天`}
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="glass-card p-4">
          <SectionTitle title="最近对话" subtitle="Conversation" />
          {dialogueLogs.length > 0 ? (
            <>
              <div className="space-y-3">
                {dialogueLogs.slice(0, dialoguePage * PAGE_SIZE).map((log, index) => (
                  <div key={index} className="space-y-2">
                    <div className="ml-auto max-w-[82%] rounded-[22px] bg-purple-500 px-4 py-3 text-sm text-white shadow-lg shadow-purple-200/50">
                      <div className="mb-1 flex justify-between gap-3 text-[10px] font-semibold text-white/62">
                        <span>你说</span>
                        <span>{new Date(log.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
                      </div>
                      <p>{log.user_input_text}</p>
                    </div>
                    <div className="max-w-[86%] rounded-[22px] bg-white/62 px-4 py-3 text-sm text-purple-800 ring-1 ring-white/70">
                      <p className="mb-1 text-[10px] font-bold text-purple-400">{figure.name}</p>
                      <p>{log.reply_text}</p>
                    </div>
                  </div>
                ))}
              </div>
              {dialogueLogs.length > PAGE_SIZE && (
                <button
                  onClick={() => setDialoguePage(dialoguePage > 1 ? 1 : Math.ceil(dialogueLogs.length / PAGE_SIZE))}
                  className="mt-3 w-full rounded-full bg-white/44 py-2 text-xs font-bold text-purple-500 ring-1 ring-white/68 hover:bg-white/60 transition-colors"
                >
                  {dialoguePage > 1 ? '收起' : `加载更多（${dialogueLogs.length - PAGE_SIZE} 条）`}
                </button>
              )}
            </>
          ) : (
            <p className="rounded-[22px] bg-white/44 py-6 text-center text-sm font-medium text-purple-400 ring-1 ring-white/68">
              暂无对话记录
            </p>
          )}
        </section>

        <section className="glass-card p-4">
          <SectionTitle title="最近事件" subtitle="Timeline" />
          {eventLogs.length > 0 ? (
            <>
              <div className="space-y-2">
                {eventLogs.slice(0, eventPage * PAGE_SIZE).map((log, index) => (
                  <div key={index} className="timeline-event">
                    <span className="timeline-event__dot" />
                    <div className="min-w-0 flex-1">
                      <div className="flex justify-between gap-3">
                        <span className="truncate text-sm font-bold text-purple-900">{log.event}</span>
                        <span className="shrink-0 text-xs font-semibold text-purple-300">
                          {new Date(log.created_at || log.timestamp || Date.now()).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                      {log.reply && <p className="mt-0.5 text-xs leading-5 text-purple-500">{log.reply}</p>}
                    </div>
                  </div>
                ))}
              </div>
              {eventLogs.length > PAGE_SIZE && (
                <button
                  onClick={() => setEventPage(eventPage > 1 ? 1 : Math.ceil(eventLogs.length / PAGE_SIZE))}
                  className="mt-3 w-full rounded-full bg-white/44 py-2 text-xs font-bold text-purple-500 ring-1 ring-white/68 hover:bg-white/60 transition-colors"
                >
                  {eventPage > 1 ? '收起' : `加载更多（${eventLogs.length - PAGE_SIZE} 条）`}
                </button>
              )}
            </>
          ) : (
            <p className="rounded-[22px] bg-white/44 py-6 text-center text-sm font-medium text-purple-400 ring-1 ring-white/68">
              暂无事件记录
            </p>
          )}
        </section>
      </div>
    </div>
  )
}
