// pages/CreateSoulPage.tsx - 对话式创建：对着中央手办聊天式唤醒
import { useState, useEffect, useRef, type ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiSouls, apiVoice, apiFigures, apiBases, apiCharacter, Archetype, CharacterProfile, Recommendation, FigureProfile } from '../services/api'
import StarField from '../components/StarField'
import LiquidGlassPanel from '../components/LiquidGlassPanel'

interface Speaker {
  speaker_id: string
  name: string
  gender: string
  age_group: string
  category: string
  emotions: string[]
  demo_url: string
  description?: string
  styles?: string[]
  recommended_archetypes?: string[]
}

const ACTION_LABELS: Record<string, { label: string; action: string }> = {
  figure_placed: { label: '放上底座', action: 'short_reply' },
  light_touch: { label: '轻触', action: 'short_reply' },
  heavy_press: { label: '重按', action: 'short_reply' },
  double_tap: { label: '双击', action: 'enter_listening_once' },
  long_press: { label: '长按', action: 'enter_continuous_companion' },
}

const TOUCH_REACTIONS_TEMPLATE = [
  { key: 'figure_placed', label: '放上底座', default: '你回来了。' },
  { key: 'light_touch', label: '轻触', default: '嗯？想我了？' },
  { key: 'heavy_press', label: '重按', default: '轻一点，我不喜欢被粗暴对待。' },
  { key: 'double_tap', label: '双击', default: '说吧，这次又遇到什么事了？' },
  { key: 'long_press', label: '长按', default: '我会一直听你说，慢慢来。' },
]

const GENERATE_STATES = {
  IDLE: 'idle',
  GENERATING: 'generating',
  COMPLETED: 'completed',
  FAILED: 'failed',
} as const

type GenerateState = typeof GENERATE_STATES[keyof typeof GENERATE_STATES]

const GENERATE_MESSAGES = [
  '正在唤醒TA的灵魂…',
  '编织命运之线…',
  '注入生命能量…',
  '赋予独特记忆…',
  '即将完成觉醒…',
]

const CHAT_STAGES = {
  NAME: 'name',
  IMAGE: 'image',
  ONELINE: 'oneline',
  GENERATING: 'generating',
  REVEAL: 'reveal',
} as const

type ChatStage = typeof CHAT_STAGES[keyof typeof CHAT_STAGES]
type BaseGateState = 'checking' | 'bound' | 'unbound'

const CREATE_BASE_ID = 'BASE-001'
const FIGURE_BASE_SRC = '/lingou_figure_soul_base_clean.png'

function generateDefaultWakeNames(name: string): string[] {
  const baseName = name.trim().slice(0, 8)
  if (!baseName) return []
  return Array.from(new Set([
    baseName,
    `${baseName}醒醒`,
    `灵偶${baseName}`,
  ].map(n => n.slice(0, 8))))
}

const AVATAR_CROP_WIDTH = 900
const AVATAR_CROP_HEIGHT = 1125

function cropAvatarToPortrait(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith('image/')) {
      reject(new Error('请选择图片文件'))
      return
    }
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('图片读取失败'))
    reader.onload = () => {
      const image = new Image()
      image.onerror = () => reject(new Error('图片加载失败'))
      image.onload = () => {
        const targetRatio = AVATAR_CROP_WIDTH / AVATAR_CROP_HEIGHT
        const sourceRatio = image.width / image.height
        let sx = 0, sy = 0, sw = image.width, sh = image.height
        if (sourceRatio > targetRatio) {
          sw = image.height * targetRatio
          sx = (image.width - sw) / 2
        } else {
          sh = image.width / targetRatio
          sy = Math.max(0, Math.min(image.height - sh, (image.height - sh) * 0.18))
        }
        const canvas = document.createElement('canvas')
        canvas.width = AVATAR_CROP_WIDTH
        canvas.height = AVATAR_CROP_HEIGHT
        const ctx = canvas.getContext('2d')
        if (!ctx) { reject(new Error('图片处理失败')); return }
        ctx.fillStyle = '#fbf8ff'
        ctx.fillRect(0, 0, canvas.width, canvas.height)
        ctx.imageSmoothingQuality = 'high'
        ctx.drawImage(image, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height)
        resolve(canvas.toDataURL('image/jpeg', 0.88))
      }
      image.src = String(reader.result || '')
    }
    reader.readAsDataURL(file)
  })
}

type ToastType = { message: string; type: 'info' | 'error' | 'success' } | null

export default function CreateSoulPage() {
  const navigate = useNavigate()
  const [chatStage, setChatStage] = useState<ChatStage>(CHAT_STAGES.NAME)
  const [showFineTune, setShowFineTune] = useState(false)
  const [baseGateState, setBaseGateState] = useState<BaseGateState>('checking')
  const [baseId, setBaseId] = useState(CREATE_BASE_ID)

  const [archetypes, setArchetypes] = useState<Archetype[]>([])
  const [speakers, setSpeakers] = useState<Speaker[]>([])
  const [existingFigures, setExistingFigures] = useState<FigureProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [toast, setToast] = useState<ToastType>(null)

  const [figureName, setFigureName] = useState('')
  const [editingName, setEditingName] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const [oneLine, setOneLine] = useState('')
  const [avatarUrl, setAvatarUrl] = useState('')
  const [avatarProcessing, setAvatarProcessing] = useState(false)
  const [wakeNames, setWakeNames] = useState<string[]>([])

  const [recommendation, setRecommendation] = useState<Recommendation | null>(null)
  const [generatedCharacter, setGeneratedCharacter] = useState<CharacterProfile | null>(null)
  const [generateState, setGenerateState] = useState<GenerateState>(GENERATE_STATES.IDLE)
  const [generateMessageIndex, setGenerateMessageIndex] = useState(0)

  const [selectedArchetype, setSelectedArchetype] = useState<Archetype | null>(null)
  const [selectedSpeaker, setSelectedSpeaker] = useState<Speaker | null>(null)
  const [playingDemo, setPlayingDemo] = useState<string | null>(null)
  const [genderFilter, setGenderFilter] = useState<'all' | 'female' | 'male'>('all')
  const [categoryFilter, setCategoryFilter] = useState<string>('all')

  const [touchReactions, setTouchReactions] = useState<Record<string, { reply: string; action: string }>>(
    Object.fromEntries(TOUCH_REACTIONS_TEMPLATE.map(t => [t.key, { reply: t.default, action: ACTION_LABELS[t.key].action }]))
  )
  const [touchEscalation, setTouchEscalation] = useState<Record<string, { tier2: string[]; tier3: string[] }>>({})

  const [creating, setCreating] = useState(false)

  const chatEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const demoAudioRef = useRef<HTMLAudioElement | null>(null)

  function showToast(message: string, type: 'info' | 'error' | 'success' = 'info') {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  useEffect(() => {
    async function loadData() {
      try {
        const [archs, spks, figs, baseResp] = await Promise.all([
          apiSouls.getArchetypes(),
          apiVoice.listSpeakers(),
          apiFigures.list().catch(() => []),
          apiBases.get(CREATE_BASE_ID).catch(() => null),
        ])
        setArchetypes(archs)
        setSpeakers(spks?.speakers || [])
        setExistingFigures(figs || [])
        if (baseResp?.base) {
          setBaseId(baseResp.base.base_id || CREATE_BASE_ID)
          setBaseGateState('bound')
        } else {
          setBaseGateState('unbound')
        }
        if (archs.length > 0) setSelectedArchetype(archs[0])
        if (spks?.speakers?.length > 0) setSelectedSpeaker(spks.speakers[0])
      } catch (e: any) {
        setError(e.message || '加载失败')
        setBaseGateState('unbound')
      }
      setLoading(false)
    }
    loadData()
  }, [])

  useEffect(() => {
    if (generateState === GENERATE_STATES.GENERATING) {
      const interval = setInterval(() => {
        setGenerateMessageIndex(prev => (prev + 1) % GENERATE_MESSAGES.length)
      }, 3000)
      return () => clearInterval(interval)
    }
  }, [generateState])

  useEffect(() => {
    if (figureName.trim()) {
      const defaults = generateDefaultWakeNames(figureName)
      if (wakeNames.length === 0 || wakeNames.every(n => defaults.includes(n))) {
        setWakeNames(defaults)
      }
    }
  }, [figureName])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatStage])

  function validateWakeNames(): string {
    if (wakeNames.length === 0) return '至少需要保留一个唤醒名'
    for (const name of wakeNames) {
      if (!name.trim()) return '唤醒名不能为空'
      if (name.length > 8) return '单个唤醒名不能超过8个字'
    }
    const currentSet = new Set(wakeNames.map(n => n.trim().toLowerCase()))
    for (const fig of existingFigures) {
      if (fig.wake_names && fig.wake_names.length > 0) {
        const otherSet = new Set(fig.wake_names.map((n: string) => n.trim().toLowerCase()))
        if (currentSet.size === otherSet.size && [...currentSet].every(n => otherSet.has(n))) {
          return `唤醒名组合与「${fig.name}」完全重复，请修改`
        }
      }
    }
    return ''
  }

  function handleWakeNameChange(index: number, value: string) {
    setWakeNames(prev => prev.map((name, i) => i === index ? value.slice(0, 8) : name))
  }

  function handleOpenNameEdit() {
    setNameDraft(figureName)
    setEditingName(true)
  }

  function handleApplyNameEdit() {
    const nextName = nameDraft.trim().slice(0, 12)
    if (!nextName) {
      showToast('名字不能为空', 'error')
      return
    }
    const previousName = figureName.trim()
    const previousDefaults = generateDefaultWakeNames(previousName)
    const nextDefaults = generateDefaultWakeNames(nextName)

    setFigureName(nextName)
    setGeneratedCharacter(prev => prev ? { ...prev, name: nextName } : prev)
    setWakeNames(prev => {
      const usingDefaultWakeNames = previousDefaults.length > 0
        && prev.length === previousDefaults.length
        && prev.every((name, index) => name === previousDefaults[index])

      if (prev.length === 0 || usingDefaultWakeNames) return nextDefaults
      if (prev[0]?.trim() === previousName) return [nextDefaults[0], ...prev.slice(1)]
      return prev
    })
    setEditingName(false)
    showToast('名字已更新', 'success')
  }

  function handleAddWakeName() {
    setWakeNames(prev => [...prev, ''].slice(0, 5))
  }

  function handleRemoveWakeName(index: number) {
    setWakeNames(prev => prev.filter((_, i) => i !== index))
  }

  function handleNameSubmit() {
    if (!figureName.trim()) {
      showToast('请先告诉我你的名字呀~', 'error')
      return
    }
    setChatStage(CHAT_STAGES.IMAGE)
  }

  function handleImageSkip() {
    setChatStage(CHAT_STAGES.ONELINE)
  }

  async function handleAvatarChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setAvatarProcessing(true)
    try {
      const nextAvatar = await cropAvatarToPortrait(file)
      setAvatarUrl(nextAvatar)
      showToast('图片已自动裁剪', 'success')
      setTimeout(() => setChatStage(CHAT_STAGES.ONELINE), 600)
    } catch (e: any) {
      showToast(e.message || '图片处理失败', 'error')
    } finally {
      setAvatarProcessing(false)
    }
  }

  function handleOneLineSubmit() {
    if (!oneLine.trim()) {
      showToast('用一句话描述我吧~', 'error')
      return
    }
    handleGenerateProfile()
  }

  async function handleGenerateProfile() {
    if (baseGateState !== 'bound') {
      showToast('请先绑定灵偶底座，再开始唤醒仪式', 'error')
      return
    }
    if (!figureName.trim() || !oneLine.trim()) return
    setChatStage(CHAT_STAGES.GENERATING)
    setGenerateState(GENERATE_STATES.GENERATING)
    setGenerateMessageIndex(0)
    setError('')

    const msgInterval = setInterval(() => {
      setGenerateMessageIndex(prev => (prev + 1) % GENERATE_MESSAGES.length)
    }, 4000)

    try {
      const result = await apiCharacter.generate({
        name: figureName.trim(),
        figure_type: 'soul',
        archetype: selectedArchetype?.archetype || '软萌治愈型',
        one_line: oneLine,
      }, 70000)

      clearInterval(msgInterval)
      setRecommendation(result.recommendation)
      setGeneratedCharacter(result.character_profile)

      const recommendedArch = archetypes.find(a => a.archetype === result.recommendation.recommended_archetype)
      if (recommendedArch) {
        setSelectedArchetype(recommendedArch)
        const archVoice = recommendedArch.volcano_speaker || recommendedArch.recommended_voice
        if (archVoice) {
          const recommendedSpk = speakers.find(s => s.speaker_id === archVoice)
          if (recommendedSpk) setSelectedSpeaker(recommendedSpk)
        }
      }
      const recommendedSpk = speakers.find(s => s.speaker_id === result.recommendation.recommended_voice)
      if (recommendedSpk) setSelectedSpeaker(recommendedSpk)

      const touchReactionsData = result.recommendation.recommended_touch_reactions
      const newTouchReactions: Record<string, { reply: string; action: string }> = {}
      for (const key of ['figure_placed', 'light_touch', 'heavy_press', 'double_tap', 'long_press'] as const) {
        newTouchReactions[key] = {
          reply: touchReactionsData[key],
          action: ACTION_LABELS[key]?.action || 'short_reply',
        }
      }
      setTouchReactions(newTouchReactions)
      setTouchEscalation(result.recommendation.recommended_touch_escalation || {})

      setGenerateState(GENERATE_STATES.COMPLETED)
      setChatStage(CHAT_STAGES.REVEAL)
    } catch (e: any) {
      clearInterval(msgInterval)
      const msg = e?.message || ''
      if (msg.includes('timeout') || msg.includes('Timeout') || msg.includes('aborted')) {
        showToast('生成超时（>70秒），请重试', 'error')
      } else {
        showToast(e?.message || '生成失败，请重试', 'error')
      }
      setGenerateState(GENERATE_STATES.FAILED)
      setChatStage(CHAT_STAGES.ONELINE)
    }
  }

  function playDemoAudio(speaker: Speaker) {
    if (playingDemo === speaker.speaker_id) {
      demoAudioRef.current?.pause()
      setPlayingDemo(null)
      return
    }
    if (demoAudioRef.current) demoAudioRef.current.pause()
    setPlayingDemo(speaker.speaker_id)
    const audio = new Audio(speaker.demo_url)
    demoAudioRef.current = audio
    audio.onended = () => setPlayingDemo(null)
    audio.onerror = () => setPlayingDemo(null)
    audio.play().catch(() => setPlayingDemo(null))
  }

  async function handleCreate() {
    if (baseGateState !== 'bound') {
      showToast('请先绑定灵偶底座，再保存灵偶', 'error')
      return
    }
    if (!selectedArchetype || !figureName.trim() || !selectedSpeaker) return
    const wakeError = validateWakeNames()
    if (wakeError) {
      showToast(wakeError, 'error')
      return
    }
    setCreating(true)
    setError('')
    try {
      const arch = selectedArchetype as any
      const figure = await apiFigures.create({
        name: figureName.trim(),
        figure_type: 'soul',
        avatar_url: avatarUrl,
        wake_names: wakeNames,
        soul_profile: {
          archetype: selectedArchetype.archetype,
          name: figureName.trim(),
          avatar_url: avatarUrl,
          address_user_as: 'Eddie',
          one_line: oneLine,
          persona: {
            traits: arch.personality_traits || [],
            greeting: recommendation?.wake_reply || arch.greeting || '你好~',
            speaking_style: arch.speaking_style || 'cute',
            response_templates: arch.response_templates || {},
          },
          character_profile: generatedCharacter || undefined,
        },
        voice_profile: {
          speaker: selectedSpeaker.speaker_id,
        },
        touch_reactions: touchReactions,
        touch_escalation: touchEscalation,
      })

      if (generatedCharacter) {
        await apiFigures.saveCharacter(figure.figure_id, generatedCharacter)
      }

      try {
        await apiBases.setActiveFigure(baseId, figure.figure_id)
      } catch {}

      navigate(`/soul/${figure.figure_id}`)
    } catch (e: any) {
      setError(e.message || '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const availableCategories = Array.from(new Set(speakers.map(s => s.category))).sort()
  const filteredSpeakers = speakers.filter(s => {
    if (genderFilter !== 'all' && s.gender !== genderFilter) return false
    if (categoryFilter !== 'all' && s.category !== categoryFilter) return false
    return true
  })
  const hasNameReply = chatStage !== CHAT_STAGES.NAME
  const hasImageReply = chatStage === CHAT_STAGES.ONELINE || chatStage === CHAT_STAGES.GENERATING || chatStage === CHAT_STAGES.REVEAL
  const hasOneLineReply = chatStage === CHAT_STAGES.GENERATING || chatStage === CHAT_STAGES.REVEAL
  const selectedVoiceName = selectedSpeaker?.name || recommendation?.recommended_voice || 'AI 推荐声线'
  const relationshipEntries = Object.entries(generatedCharacter?.relationships || {})
  const signatureLines = generatedCharacter?.signature_lines || []

  if (loading) {
    return (
      <div className="min-h-screen bg-castle relative flex items-center justify-center overflow-hidden">
        <StarField count={16} />
        <div className="relative z-10 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-white/80 text-2xl shadow-soul">✦</div>
          <p className="text-sm font-semibold text-purple-500">召唤素材加载中…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="create-ritual-page">
      <StarField count={22} />
      <div className="create-ritual-orb create-ritual-orb--top" />
      <div className="create-ritual-orb create-ritual-orb--bottom" />

      <div className="create-ritual-shell">
        <header className="create-ritual-header">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="create-ritual-back"
            aria-label="返回"
          >
            ←
          </button>
          <div>
            <p className="create-ritual-kicker">SOUL AWAKENING</p>
            <h1>唤醒灵偶</h1>
            <span>聊两句，给 TA 一张图，就能生成完整灵魂档案。</span>
          </div>
          <div className={`create-base-pill create-base-pill--${baseGateState}`}>
            {baseGateState === 'bound' ? baseId : baseGateState === 'checking' ? '检测中' : '未绑定'}
          </div>
        </header>

        <section className={`create-awakening-stage ${
          chatStage === CHAT_STAGES.GENERATING ? 'create-awakening-stage--charging' : ''
        } ${chatStage === CHAT_STAGES.REVEAL ? 'create-awakening-stage--awake' : ''}`}>
          <div className="create-awakening-ring" />
          <div className="create-awakening-sparks">
            <span />
            <span />
            <span />
            <span />
          </div>
          <div className="create-awakening-glass">
            <img
              src={avatarUrl || FIGURE_BASE_SRC}
              alt={avatarUrl ? `${figureName || '灵偶'}立绘` : '灵偶手办示意图'}
              className={avatarUrl ? 'create-awakening-image create-awakening-image--avatar' : 'create-awakening-image'}
            />
          </div>
          <div className="create-awakening-plinth">
            <strong>{figureName || '等待命名'}</strong>
            <span>{chatStage === CHAT_STAGES.REVEAL ? '灵魂已点亮' : '等待注入灵魂'}</span>
          </div>
          {chatStage === CHAT_STAGES.GENERATING && (
            <div className="create-awakening-charge">
              <i />
              <p>{GENERATE_MESSAGES[generateMessageIndex]}</p>
            </div>
          )}
          {chatStage === CHAT_STAGES.REVEAL && recommendation && (
            <div className="create-awakening-voice">
              “{recommendation.wake_reply}”
            </div>
          )}
        </section>

        <main className="create-chat-scroll">
          {baseGateState !== 'bound' && (
            <LiquidGlassPanel className="create-gate-card" contentClassName="p-4" radius={28} variant="hero">
              <p className="create-gate-card__eyebrow">底座未就绪</p>
              <h2>先绑定灵偶底座</h2>
              <p>创建出的灵偶会直接进入当前底座。绑定后，你仍然可以随时修改灵偶档案、音色和互动台词。</p>
              <button type="button" onClick={() => navigate('/bind')}>去绑定底座</button>
            </LiquidGlassPanel>
          )}

          {baseGateState === 'bound' && (
            <div className="create-dialogue-stack">
              <div className="create-bubble-row create-bubble-row--bot">
                <span className="create-bubble-avatar">✦</span>
                <LiquidGlassPanel className="create-bubble create-bubble--bot" contentClassName="p-3" radius={22}>
                  <p>你好呀~你想叫我什么名字？</p>
                </LiquidGlassPanel>
              </div>

              {chatStage === CHAT_STAGES.NAME ? (
                <div className="create-answer-panel">
                  <input
                    type="text"
                    value={figureName}
                    maxLength={12}
                    onChange={(e) => setFigureName(e.target.value.slice(0, 12))}
                    onKeyDown={(e) => e.key === 'Enter' && handleNameSubmit()}
                    placeholder="给 TA 起个名字"
                    autoFocus
                  />
                  <button type="button" onClick={handleNameSubmit}>就叫这个名字</button>
                </div>
              ) : hasNameReply && (
                <div className="create-bubble-row create-bubble-row--user">
                  <div className="create-bubble create-bubble--user">叫你「{figureName}」</div>
                </div>
              )}

              {hasNameReply && (
                <div className="create-bubble-row create-bubble-row--bot">
                  <span className="create-bubble-avatar">✦</span>
                  <LiquidGlassPanel className="create-bubble create-bubble--bot" contentClassName="p-3" radius={22}>
                    <p>我长什么样？给我看看吧 📷</p>
                    <small>本期只作为立绘/头像展示，不做图片识别。</small>
                  </LiquidGlassPanel>
                </div>
              )}

              {chatStage === CHAT_STAGES.IMAGE ? (
                <div className="create-answer-panel">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    onChange={handleAvatarChange}
                    className="hidden"
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={avatarProcessing}
                  >
                    {avatarProcessing ? '正在裁剪图片…' : '上传图片'}
                  </button>
                  <button type="button" className="create-answer-panel__ghost" onClick={handleImageSkip}>
                    先跳过，以后再换
                  </button>
                </div>
              ) : hasImageReply && (
                <div className="create-bubble-row create-bubble-row--user">
                  <div className="create-bubble create-bubble--user">
                    {avatarUrl ? '已经给你准备好立绘了' : '先用灵偶底座示意图'}
                  </div>
                </div>
              )}

              {hasImageReply && (
                <div className="create-bubble-row create-bubble-row--bot">
                  <span className="create-bubble-avatar">✦</span>
                  <LiquidGlassPanel className="create-bubble create-bubble--bot" contentClassName="p-3" radius={22}>
                    <p>用一句话告诉我，我是个怎样的存在？</p>
                  </LiquidGlassPanel>
                </div>
              )}

              {chatStage === CHAT_STAGES.ONELINE ? (
                <div className="create-answer-panel">
                  <textarea
                    value={oneLine}
                    onChange={(e) => setOneLine(e.target.value.slice(0, 30))}
                    placeholder="例如：会在我低落时温柔陪我的姐姐"
                    rows={3}
                    autoFocus
                  />
                  <div className="create-answer-panel__footer">
                    <span>{oneLine.length}/30</span>
                    <button type="button" onClick={handleOneLineSubmit}>✦ 注入灵魂 ✦</button>
                  </div>
                </div>
              ) : hasOneLineReply && (
                <div className="create-bubble-row create-bubble-row--user">
                  <div className="create-bubble create-bubble--user">{oneLine}</div>
                </div>
              )}

              {chatStage === CHAT_STAGES.GENERATING && (
                <LiquidGlassPanel className="create-generating-card" contentClassName="p-5" radius={30} variant="hero">
                  <div className="create-generating-card__sigil">✦</div>
                  <h2>正在注入灵魂</h2>
                  <p>{GENERATE_MESSAGES[generateMessageIndex]}</p>
                </LiquidGlassPanel>
              )}

              {chatStage === CHAT_STAGES.REVEAL && generatedCharacter && recommendation && (
                <section className="create-contract">
                  <div className="create-contract__title">
                    <span>✦ 灵魂契约已缔结 ✦</span>
                    {editingName ? (
                      <div className="create-name-editor">
                        <input
                          value={nameDraft}
                          maxLength={12}
                          onChange={event => setNameDraft(event.target.value.slice(0, 12))}
                          onKeyDown={event => event.key === 'Enter' && handleApplyNameEdit()}
                          placeholder="新的灵偶名字"
                          autoFocus
                        />
                        <div>
                          <button type="button" onClick={handleApplyNameEdit}>保存名字</button>
                          <button type="button" onClick={() => setEditingName(false)}>取消</button>
                        </div>
                      </div>
                    ) : (
                      <div className="create-contract-name">
                        <h2>{figureName}</h2>
                        <button type="button" onClick={handleOpenNameEdit}>改名</button>
                      </div>
                    )}
                    <p>{recommendation.recommended_archetype} · {selectedVoiceName}</p>
                  </div>

                  <LiquidGlassPanel className="create-contract-card" contentClassName="p-4" radius={30} variant="hero">
                    <p className="create-contract-card__label">第一句话</p>
                    <strong>“{recommendation.wake_reply}”</strong>
                    <small>创建后可随时在编辑页修改档案、音色和互动台词。</small>
                  </LiquidGlassPanel>

                  <div className="create-contract-grid">
                    <LiquidGlassPanel className="create-contract-card" contentClassName="p-4" radius={26}>
                      <p className="create-contract-card__label">气质</p>
                      <strong>{recommendation.recommended_archetype}</strong>
                      <div className="create-chip-row">
                        {recommendation.personality_traits.slice(0, 4).map((trait, index) => (
                          <span key={index}>{trait}</span>
                        ))}
                      </div>
                    </LiquidGlassPanel>

                    <LiquidGlassPanel className="create-contract-card" contentClassName="p-4" radius={26}>
                      <p className="create-contract-card__label">说话方式</p>
                      <strong>{recommendation.speech_style}</strong>
                      <div className="create-chip-row">
                        {(generatedCharacter.catchphrases || []).slice(0, 3).map((line, index) => (
                          <span key={index}>{line}</span>
                        ))}
                      </div>
                    </LiquidGlassPanel>
                  </div>

                  {signatureLines.length > 0 && (
                    <LiquidGlassPanel className="create-contract-card" contentClassName="p-4" radius={26}>
                      <p className="create-contract-card__label">代表台词</p>
                      <div className="create-line-list">
                        {signatureLines.slice(0, 3).map((line, index) => (
                          <p key={index}>“{line}”</p>
                        ))}
                      </div>
                    </LiquidGlassPanel>
                  )}

                  {relationshipEntries.length > 0 && (
                    <LiquidGlassPanel className="create-contract-card" contentClassName="p-4" radius={26}>
                      <p className="create-contract-card__label">关系网</p>
                      <div className="create-relation-list">
                        {relationshipEntries.slice(0, 4).map(([relation, target]) => (
                          <span key={relation}>{relation}: {target}</span>
                        ))}
                      </div>
                    </LiquidGlassPanel>
                  )}

                  <button
                    type="button"
                    onClick={() => setShowFineTune(!showFineTune)}
                    className="create-finetune-toggle"
                  >
                    {showFineTune ? '收起细节微调 ▲' : '细节微调 ▼'}
                  </button>

                  {showFineTune && (
                    <div className="create-finetune">
                      <LiquidGlassPanel className="create-finetune-card" contentClassName="p-4" radius={26}>
                        <h3>人格气质</h3>
                        <div className="create-chip-row create-chip-row--select">
                          {archetypes.map(arch => (
                            <button
                              key={arch.archetype}
                              type="button"
                              onClick={() => setSelectedArchetype(arch)}
                              className={selectedArchetype?.archetype === arch.archetype ? 'is-selected' : ''}
                            >
                              {arch.archetype}
                            </button>
                          ))}
                        </div>
                      </LiquidGlassPanel>

                      <LiquidGlassPanel className="create-finetune-card" contentClassName="p-4" radius={26}>
                        <h3>唤醒名</h3>
                        <div className="create-wake-list">
                          {wakeNames.map((name, index) => (
                            <div key={index} className="create-wake-row">
                              <input
                                value={name}
                                onChange={event => handleWakeNameChange(index, event.target.value)}
                                placeholder="唤醒名"
                              />
                              <button type="button" onClick={() => handleRemoveWakeName(index)}>删除</button>
                            </div>
                          ))}
                        </div>
                        {wakeNames.length < 5 && (
                          <button type="button" className="create-finetune-add" onClick={handleAddWakeName}>
                            + 新增唤醒名
                          </button>
                        )}
                      </LiquidGlassPanel>

                      <LiquidGlassPanel className="create-finetune-card" contentClassName="p-4" radius={26}>
                        <h3>声音选择</h3>
                        <div className="create-filter-row">
                          {(['all', 'female', 'male'] as const).map(g => (
                            <button
                              key={g}
                              type="button"
                              onClick={() => setGenderFilter(g)}
                              className={genderFilter === g ? 'is-selected' : ''}
                            >
                              {g === 'all' ? '全部' : g === 'female' ? '女声' : '男声'}
                            </button>
                          ))}
                        </div>
                        <select value={categoryFilter} onChange={event => setCategoryFilter(event.target.value)}>
                          <option value="all">全部分类</option>
                          {availableCategories.map(category => (
                            <option key={category} value={category}>{category}</option>
                          ))}
                        </select>
                        <div className="create-speaker-list">
                          {filteredSpeakers.slice(0, 24).map(spk => (
                            <div
                              key={spk.speaker_id}
                              className={`create-speaker-row ${selectedSpeaker?.speaker_id === spk.speaker_id ? 'is-selected' : ''}`}
                            >
                              <button type="button" onClick={() => setSelectedSpeaker(spk)}>
                                <strong>{spk.name}</strong>
                                <span>{spk.description || `${spk.gender === 'female' ? '女声' : '男声'} · ${spk.category}`}</span>
                              </button>
                              <button type="button" onClick={() => playDemoAudio(spk)}>
                                {playingDemo === spk.speaker_id ? '暂停' : '试听'}
                              </button>
                            </div>
                          ))}
                        </div>
                      </LiquidGlassPanel>

                      <LiquidGlassPanel className="create-finetune-card" contentClassName="p-4" radius={26}>
                        <h3>触摸台词</h3>
                        <div className="create-touch-list">
                          {TOUCH_REACTIONS_TEMPLATE.map(item => (
                            <label key={item.key}>
                              <span>{item.label}</span>
                              <textarea
                                value={touchReactions[item.key]?.reply || ''}
                                onChange={event => setTouchReactions(prev => ({
                                  ...prev,
                                  [item.key]: {
                                    reply: event.target.value,
                                    action: prev[item.key]?.action || ACTION_LABELS[item.key].action,
                                  },
                                }))}
                                rows={2}
                              />
                            </label>
                          ))}
                        </div>
                      </LiquidGlassPanel>
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={handleCreate}
                    disabled={creating}
                    className="create-save-button"
                  >
                    {creating ? '保存中…' : '保存灵偶，开始陪伴'}
                  </button>
                </section>
              )}

              <div ref={chatEndRef} />
            </div>
          )}
        </main>
      </div>

      {toast && (
        <div className={`create-toast create-toast--${toast.type}`}>
          {toast.message}
        </div>
      )}

      {error && (
        <div className="create-error-toast">
          {error}
        </div>
      )}
    </div>
  )
}
