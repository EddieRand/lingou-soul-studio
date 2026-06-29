// pages/EditSoulPage.tsx - 二次编辑灵偶（/soul/:id/edit）
import { useState, useEffect, useMemo, useRef, type ChangeEvent } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { apiFigures, apiVoice, apiSouls, Archetype } from '../services/api'
import StarField from '../components/StarField'
import PageHeader from '../components/PageHeader'
import ArchetypeCrest from '../components/ArchetypeCrest'
import Waveform from '../components/Waveform'
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

interface SpeakerCategory {
  key: string
  gender: string
  category: string
  speakers: Speaker[]
}

const ADDRESS_CHIPS = ['Eddie', '主人', '搭档', '师父', '朋友']

const ACTION_LABELS: Record<string, { label: string; action: string }> = {
  figure_placed: { label: '放上底座', action: 'short_reply' },
  light_touch: { label: '轻触', action: 'short_reply' },
  heavy_press: { label: '重按', action: 'short_reply' },
  double_tap: { label: '双击', action: 'enter_listening_once' },
  long_press: { label: '长按', action: 'enter_continuous_companion' },
}

const TOUCH_REACTIONS_TEMPLATE = [
  { key: 'figure_placed', label: '放上底座', icon: '🏠', default: '你回来了。', actionLabel: '短回应' },
  { key: 'light_touch', label: '轻触', icon: '👆', default: '嗯？想我了？', actionLabel: '短回应' },
  { key: 'heavy_press', label: '重按', icon: '✋', default: '轻一点，我不喜欢被粗暴对待。', actionLabel: '短回应' },
  { key: 'double_tap', label: '双击', icon: '✌️', default: '说吧，这次又遇到什么事了？', actionLabel: '启动一次对话' },
  { key: 'long_press', label: '长按', icon: '⏱', default: '我会一直听你说，慢慢来。', actionLabel: '持续陪伴' },
]

type ToastType = { message: string; type: 'info' | 'error' | 'success' } | null

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
        let sx = 0
        let sy = 0
        let sw = image.width
        let sh = image.height

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
        if (!ctx) {
          reject(new Error('图片处理失败'))
          return
        }

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

export default function EditSoulPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [error, setError] = useState('')
  const [toast, setToast] = useState<ToastType>(null)
  const [figure, setFigure] = useState<any>(null)
  const [avatarUrl, setAvatarUrl] = useState('')
  const [avatarProcessing, setAvatarProcessing] = useState(false)

  // Step 1: 基础
  const [figureName, setFigureName] = useState('')
  const [addressUserAs, setAddressUserAs] = useState('Eddie')
  const [customAddress, setCustomAddress] = useState('')
  const [wakeNames, setWakeNames] = useState<string[]>([])
  const [wakeNameError, setWakeNameError] = useState('')

  // Step 2: 人格与声音
  const [archetypes, setArchetypes] = useState<Archetype[]>([])
  const [selectedArchetype, setSelectedArchetype] = useState<Archetype | null>(null)
  const [selectedSpeaker, setSelectedSpeaker] = useState<Speaker | null>(null)
  const [playing, setPlaying] = useState<string | null>(null)

  // Step 3: 触摸反应
  const [touchReactions, setTouchReactions] = useState<Record<string, { reply: string; action: string }>>(
    Object.fromEntries(TOUCH_REACTIONS_TEMPLATE.map(t => [t.key, { reply: t.default, action: ACTION_LABELS[t.key].action }]))
  )
  const [editingTouchKey, setEditingTouchKey] = useState<string | null>(null)
  const [editingTouchReply, setEditingTouchReply] = useState('')
  const [showTouchEditModal, setShowTouchEditModal] = useState(false)

  // 深度字段（灵魂档案）
  const [relationships, setRelationships] = useState<Record<string, string>>({})
  const [traits, setTraits] = useState<string[]>([])
  const [values, setValues] = useState<string[]>([])
  const [knowledgeBounds, setKnowledgeBounds] = useState<{ knows: string[]; unknowns: string[] }>({ knows: [], unknowns: [] })
  const [catchphrases, setCatchphrases] = useState<string[]>([])
  const [signatureLines, setSignatureLines] = useState<string[]>([])
  const [taboos, setTaboos] = useState<string[]>([])
  const [speakerCategories, setSpeakerCategories] = useState<SpeakerCategory[]>([])
  const [genderFilter, setGenderFilter] = useState<'all' | 'female' | 'male'>('all')
  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [playingDemo, setPlayingDemo] = useState<string | null>(null)

  // 声音克隆
  const [cloneStatus, setCloneStatus] = useState<'not_cloned' | 'cloning' | 'ready' | 'failed'>('not_cloned')
  const [uploadedAudioName, setUploadedAudioName] = useState<string | null>(null)
  const [consentAgreed, setConsentAgreed] = useState(false)
  const [audioDuration, setAudioDuration] = useState<number | null>(null)
  const [promptText, setPromptText] = useState('')

  function showToast(message: string, type: 'info' | 'error' | 'success' = 'info') {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  useEffect(() => {
    if (!id) return
    const figureId: string = id
    async function loadData() {
      try {
        const [fig, archs, spks] = await Promise.all([
          apiFigures.get(figureId),
          apiSouls.getArchetypes(),
          apiVoice.listSpeakers(),
        ])
        setFigure(fig)
        setArchetypes(archs)
        setSpeakerCategories(spks?.categories || [])
        setAvatarUrl(fig.avatar_url || fig.soul_profile?.avatar_url || '')

        // 填充现有数据
        setFigureName(fig.name || '')
        const soul = fig.soul_profile || {}
        setAddressUserAs(soul.address_user_as || 'Eddie')
        setWakeNames(fig.wake_names || [])

        // 人格
        const arch = archs.find((a: Archetype) => a.archetype === soul.archetype)
        if (arch) setSelectedArchetype(arch)

        // 音色
        const voice = fig.voice_profile || {}
        const spk = (spks?.speakers || []).find((s: Speaker) => s.speaker_id === voice.speaker)
        if (spk) setSelectedSpeaker(spk)

        // 触摸反应
        const reactions = fig.touch_reactions || {}
        const merged: Record<string, { reply: string; action: string }> = {}
        for (const t of TOUCH_REACTIONS_TEMPLATE) {
          merged[t.key] = {
            reply: reactions[t.key]?.[0] || t.default,
            action: ACTION_LABELS[t.key].action,
          }
        }
        setTouchReactions(merged)

        // 深度字段（灵魂档案）
        const characterProfile = fig.soul_profile?.character_profile || {}
        setRelationships(characterProfile.relationships || {})
        setTraits(characterProfile.traits || [])
        setValues(characterProfile.values || [])
        setKnowledgeBounds(characterProfile.knowledge_bounds || { knows: [], unknowns: [] })
        setCatchphrases(characterProfile.catchphrases || [])
        setSignatureLines(characterProfile.signature_lines || [])
        setTaboos(characterProfile.taboos || [])
      } catch (e: any) {
        setError(e.message || '加载失败')
      }
      setLoading(false)
    }
    loadData()
  }, [id])

  function validateWakeNames(): string {
    if (wakeNames.length === 0) return '至少需要保留一个唤醒名'
    for (const name of wakeNames) {
      if (!name.trim()) return '唤醒名不能为空'
      if (name.length > 8) return '单个唤醒名不能超过8个字'
    }
    return ''
  }

  async function handleSave() {
    if (!id) return
    const wakeError = validateWakeNames()
    if (wakeError) {
      setWakeNameError(wakeError)
      showToast(wakeError, 'error')
      return
    }

    setSaving(true)
    setError('')
    try {
      // 构建更新数据
      const touchReactionsOut: Record<string, string[]> = {}
      for (const [key, val] of Object.entries(touchReactions)) {
        touchReactionsOut[key] = [val.reply]
      }

      await apiFigures.update(id, {
        name: figureName.trim(),
        avatar_url: avatarUrl,
        wake_names: wakeNames,
        soul_profile: {
          archetype: selectedArchetype?.archetype || figure?.soul_profile?.archetype,
          name: figureName.trim(),
          avatar_url: avatarUrl,
          address_user_as: customAddress || addressUserAs,
          persona: {
            traits: selectedArchetype?.personality_traits || [],
            greeting: selectedArchetype?.greeting || '你好~',
            speaking_style: selectedArchetype?.speaking_style || 'cute',
          },
          character_profile: {
            name: figureName.trim(),
            archetype: selectedArchetype?.archetype || figure?.soul_profile?.archetype || '',
            background: '',
            catchphrases,
            signature_lines: signatureLines,
            taboos,
            personality_traits: [],
            relationships,
            traits,
            values,
            knowledge_bounds: knowledgeBounds,
          },
        },
        voice_profile: {
          speaker: selectedSpeaker?.speaker_id || figure?.voice_profile?.speaker,
        },
        touch_reactions: touchReactionsOut,
      })

      await apiFigures.saveCharacter(id, {
        name: figureName.trim(),
        archetype: selectedArchetype?.archetype || figure?.soul_profile?.archetype || '',
        background: '',
        catchphrases,
        signature_lines: signatureLines,
        taboos,
        personality_traits: [],
        relationships,
        traits,
        values,
        knowledge_bounds: knowledgeBounds,
      })

      showToast('保存成功', 'success')
      setTimeout(() => navigate(`/soul/${id}`), 1000)
    } catch (e: any) {
      setError(e.message || '保存失败')
      showToast('保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!id) return
    setDeleting(true)
    try {
      await apiFigures.delete(id)
      showToast('已删除', 'success')
      setTimeout(() => navigate('/home'), 800)
    } catch (e: any) {
      showToast(e.message || '删除失败', 'error')
    } finally {
      setDeleting(false)
      setShowDeleteConfirm(false)
    }
  }

  async function handleAvatarChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return

    setAvatarProcessing(true)
    try {
      const nextAvatar = await cropAvatarToPortrait(file)
      setAvatarUrl(nextAvatar)
      showToast('图片已自动裁剪，保存后生效', 'success')
    } catch (e: any) {
      showToast(e.message || '图片处理失败', 'error')
    } finally {
      setAvatarProcessing(false)
    }
  }

  async function playVoiceSample(speaker: Speaker) {
    if (playing === speaker.speaker_id) {
      setPlaying(null)
      return
    }
    setPlaying(speaker.speaker_id)
    try {
      const tempFig = await apiFigures.create({
        name: '试听',
        figure_type: 'temp',
        wake_names: ['试听'],
        soul_profile: { archetype: '软萌治愈型' },
        voice_profile: { speaker: speaker.speaker_id },
      })
      const sample = TOUCH_REACTIONS_TEMPLATE[0].default
      const resp = await apiVoice.generate(tempFig.figure_id, sample, speaker.speaker_id)
      if (resp.audio_url) {
        const audio = new Audio(resp.audio_url)
        audio.onended = () => setPlaying(null)
        audio.onerror = () => setPlaying(null)
        await audio.play()
      } else {
        setPlaying(null)
      }
    } catch {
      setPlaying(null)
    }
  }

  const demoAudioRef = useRef<HTMLAudioElement | null>(null)

  function playDemoAudio(speaker: Speaker) {
    if (playingDemo === speaker.speaker_id) {
      demoAudioRef.current?.pause()
      setPlayingDemo(null)
      return
    }
    if (!speaker.demo_url) {
      playVoiceSample(speaker)
      return
    }
    if (demoAudioRef.current) {
      demoAudioRef.current.pause()
    }
    setPlayingDemo(speaker.speaker_id)
    const audio = new Audio(speaker.demo_url)
    demoAudioRef.current = audio
    audio.onended = () => setPlayingDemo(null)
    audio.onerror = () => {
      setPlayingDemo(null)
      playVoiceSample(speaker)
    }
    audio.play().catch(() => {
      setPlayingDemo(null)
    })
  }

  const availableCategories = useMemo(() => {
    const set = new Set<string>()
    speakerCategories.forEach(cat => set.add(cat.category))
    return Array.from(set).sort()
  }, [speakerCategories])

  const filteredSpeakers = useMemo(() => {
    let list = (speakerCategories || []).flatMap(c => c.speakers)
    if (genderFilter !== 'all') {
      list = list.filter(s => s.gender === genderFilter)
    }
    if (categoryFilter !== 'all') {
      list = list.filter(s => s.category === categoryFilter)
    }
    return list
  }, [speakerCategories, genderFilter, categoryFilter])

  function openTouchEditModal(key: string) {
    setEditingTouchKey(key)
    setEditingTouchReply(touchReactions[key]?.reply || '')
    setShowTouchEditModal(true)
  }

  function saveTouchEdit() {
    if (editingTouchKey) {
      setTouchReactions({
        ...touchReactions,
        [editingTouchKey]: {
          reply: editingTouchReply,
          action: ACTION_LABELS[editingTouchKey]?.action || 'short_reply',
        },
      })
      showToast('台词已保存', 'success')
    }
    setShowTouchEditModal(false)
    setEditingTouchKey(null)
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-castle relative flex items-center justify-center overflow-hidden">
        <StarField count={14} />
        <div className="relative z-10 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-white/80 text-2xl shadow-soul">✦</div>
          <p className="text-sm font-semibold text-purple-500">档案读取中…</p>
        </div>
      </div>
    )
  }

  if (!figure) {
    return (
    <div className="min-h-screen bg-castle flex flex-col items-center justify-center">
        <StarField count={10} />
        <p className="text-purple-400 mb-4">灵偶不存在</p>
        <button onClick={() => navigate('/home')} className="text-purple-500">返回首页</button>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-castle relative overflow-hidden">
      <StarField count={20} />
      <div className="pointer-events-none absolute -top-28 left-1/2 h-80 w-80 -translate-x-1/2 rounded-full bg-white/62 blur-3xl" />

      {/* Toast */}
      {toast && (
        <div className={`fixed top-20 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl text-sm font-medium shadow-lg animate-fade-in ${
          toast.type === 'error' ? 'bg-red-100 text-red-600 border border-red-200' :
          toast.type === 'success' ? 'bg-green-100 text-green-600 border border-green-200' :
          'bg-purple-100 text-purple-600 border border-purple-200'
        }`}>
          {toast.message}
        </div>
      )}

      <PageHeader
        title="编辑灵偶"
        subtitle={figure.name}
        onBack={() => navigate(`/soul/${id}`)}
      />

      <div className="relative z-10 mx-auto max-w-lg space-y-4 px-4 pb-44">
        {error && (
          <div className="mb-4 p-3 bg-red-50 text-red-600 rounded-xl text-sm">{error}</div>
        )}

        {/* 头像预览 */}
        <section className="edit-avatar-card">
          <div className="edit-avatar-card__stage">
            <div className="edit-soul-avatar">
            {avatarUrl ? (
              <img src={avatarUrl} alt={figureName || figure.name} />
            ) : (
              <span>{figureName ? figureName.charAt(0) : figure.name?.charAt(0) || '✦'}</span>
            )}
            </div>
          </div>
          <div className="edit-avatar-card__content">
            <p className="text-[10px] font-black uppercase tracking-[0.2em] text-purple-400">Soul Image</p>
            <h3 className="mt-1 text-base font-black text-purple-950">灵偶图片</h3>
            <p className="mt-1 text-xs font-semibold leading-5 text-purple-400">
              上传后会自动裁成适配角色卡和羁绊页的立牌比例。
            </p>
            <div className="mt-3 flex gap-2">
              <label className={`edit-avatar-card__button ${avatarProcessing ? 'is-loading' : ''}`}>
                <input
                  type="file"
                  accept="image/*"
                  className="hidden"
                  disabled={avatarProcessing}
                  onChange={handleAvatarChange}
                />
                {avatarProcessing ? '裁剪中…' : '更换图片'}
              </label>
              {avatarUrl && (
                <button
                  type="button"
                  onClick={() => setAvatarUrl('')}
                  className="edit-avatar-card__button edit-avatar-card__button--ghost"
                >
                  移除
                </button>
              )}
            </div>
          </div>
        </section>

        {/* 名字 */}
        <LiquidGlassPanel contentClassName="p-4" radius={24} variant="panel">
          <label className="block text-sm font-medium text-purple-700 mb-2">灵偶名字</label>
          <input
            type="text"
            value={figureName}
            onChange={e => setFigureName(e.target.value)}
            className="w-full px-3 py-2.5 bg-white/60 border border-purple-100 rounded-xl text-sm text-purple-900 focus:outline-none focus:ring-2 focus:ring-purple-300"
          />
        </LiquidGlassPanel>

        {/* TA 怎么称呼你 */}
        <div>
          <label className="block text-sm font-medium text-purple-700 mb-2">TA怎么称呼你</label>
          <div className="flex flex-wrap gap-2">
            {ADDRESS_CHIPS.map(chip => (
              <button
                key={chip}
                onClick={() => { setAddressUserAs(chip); setCustomAddress('') }}
                className={`chip ${addressUserAs === chip && !customAddress ? 'active' : ''}`}
              >
                {chip}
              </button>
            ))}
            <input
              type="text"
              value={customAddress}
              onChange={e => setCustomAddress(e.target.value)}
              placeholder="自定义…"
              className="px-3 py-2 bg-white/60 border border-purple-100 rounded-full text-sm text-purple-900 placeholder-purple-300 focus:outline-none focus:ring-2 focus:ring-purple-300 w-24"
            />
          </div>
        </div>

        {/* 唤醒名 */}
        <div className="glass-card p-4">
          <label className="block text-sm font-medium text-purple-700 mb-2">唤醒名</label>
          <div className="space-y-2 mb-3">
            {wakeNames.map((name, i) => (
              <div key={i} className="flex items-center gap-2">
                <input
                  type="text"
                  value={name}
                  onChange={e => {
                    const newNames = [...wakeNames]
                    newNames[i] = e.target.value
                    setWakeNames(newNames)
                  }}
                  className="flex-1 px-3 py-2 bg-white/60 border border-purple-100 rounded-xl text-sm text-purple-900 focus:outline-none focus:ring-2 focus:ring-purple-300"
                  maxLength={8}
                />
                {wakeNames.length > 1 && (
                  <button
                    onClick={() => setWakeNames(wakeNames.filter((_, idx) => idx !== i))}
                    className="w-8 h-8 rounded-full bg-red-100 text-red-500 flex items-center justify-center"
                  >×</button>
                )}
              </div>
            ))}
          </div>
          <button
            onClick={() => setWakeNames([...wakeNames, ''])}
            className="w-full py-2 bg-purple-100 text-purple-600 rounded-xl text-sm font-medium hover:bg-purple-200"
          >
            + 新增唤醒名
          </button>
          {wakeNameError && <p className="text-xs text-red-500 mt-1">{wakeNameError}</p>}
        </div>

        {/* 人格 */}
        <div>
          <h3 className="text-sm font-semibold text-purple-700 mb-2.5">人格设定</h3>
          <div className="grid grid-cols-2 gap-2.5">
            {archetypes.slice(0, 6).map(arch => {
              const selected = selectedArchetype?.archetype === arch.archetype
              return (
                <button
                  key={arch.archetype}
                  onClick={() => setSelectedArchetype(arch)}
                  className={`glass-card-light p-3 flex items-center gap-3 text-left transition-all ${
                    selected ? 'ring-2 ring-purple-400 bg-purple-50' : ''
                  }`}
                >
                  <ArchetypeCrest archetype={arch.archetype} size={36} />
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-purple-900 text-sm truncate">{arch.archetype}</p>
                    <p className="text-[11px] text-purple-400 truncate">{arch.speaking_style || '温柔'}</p>
                  </div>
                  {selected && (
                    <div className="w-5 h-5 rounded-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center text-white text-xs">✓</div>
                  )}
                </button>
              )
            })}
          </div>
        </div>

        {/* 声音 */}
        <div>
          <h3 className="text-sm font-semibold text-purple-700 mb-2.5">声音设定</h3>
          {selectedSpeaker && (
            <div className="glass-card p-4 mb-3">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-purple-900 text-sm">{selectedSpeaker.name}</span>
                </div>
                <button
                  onClick={() => playDemoAudio(selectedSpeaker)}
                  className="w-9 h-9 rounded-full bg-gradient-to-br from-purple-500 to-pink-500 text-white flex items-center justify-center"
                >
                  {playingDemo === selectedSpeaker.speaker_id ? '⏸' : '▶'}
                </button>
              </div>
              <Waveform active={playingDemo === selectedSpeaker.speaker_id} bars={50} />
            </div>
          )}

          {/* 筛选栏 */}
          <div className="space-y-2 mb-3">
            <div className="flex gap-2">
              {[
                { k: 'all', l: '全部' },
                { k: 'female', l: '女声' },
                { k: 'male', l: '男声' },
              ].map(t => (
                <button
                  key={t.k}
                  onClick={() => setGenderFilter(t.k as typeof genderFilter)}
                  className={`chip ${genderFilter === t.k ? 'active' : ''}`}
                >
                  {t.l}
                </button>
              ))}
              <select
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
                className="flex-1 bg-white/60 border border-purple-200 rounded-full px-3 py-1.5 text-xs text-purple-700 focus:outline-none focus:ring-2 focus:ring-purple-300"
              >
                <option value="all">全部分类</option>
                {availableCategories.map(cat => (
                  <option key={cat} value={cat}>{cat}</option>
                ))}
              </select>
            </div>
            <p className="text-[11px] text-purple-400 text-right">
              共 {filteredSpeakers.length} 个音色
            </p>
          </div>

          {/* 音色网格 */}
          <div className="grid grid-cols-2 gap-2 max-h-[420px] overflow-y-auto pr-1" style={{ WebkitOverflowScrolling: 'touch' }}>
            {filteredSpeakers.map(speaker => {
              const isSelected = selectedSpeaker?.speaker_id === speaker.speaker_id
              const isPlaying = playingDemo === speaker.speaker_id
              return (
                <button
                  key={speaker.speaker_id}
                  onClick={() => {
                    setSelectedSpeaker(speaker)
                  }}
                  className={`glass-card-light p-3 text-left transition-all ${
                    isSelected ? 'ring-2 ring-purple-400 bg-purple-50' : ''
                  }`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-semibold text-purple-900 text-sm truncate">{speaker.name}</span>
                    {isSelected && (
                      <div className="w-4 h-4 shrink-0 rounded-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center text-white text-[10px]">✓</div>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1 mb-1.5">
                    <span className="text-[10px] px-1.5 py-0.5 bg-purple-100 text-purple-600 rounded-full">
                      {speaker.gender === 'female' ? '女' : '男'}·{speaker.age_group}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 bg-pink-100 text-pink-600 rounded-full">
                      {speaker.category}
                    </span>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      playDemoAudio(speaker)
                    }}
                    className={`w-full py-1.5 rounded-lg text-xs flex items-center justify-center gap-1 transition-all ${
                      isPlaying ? 'bg-purple-500 text-white' : 'bg-purple-100 text-purple-600 hover:bg-purple-200'
                    }`}
                  >
                    {isPlaying ? (
                      <>⏸ 试听中</>
                    ) : (
                      <>▶ 试听</>
                    )}
                  </button>
                </button>
              )
            })}
          </div>
        </div>

        {/* 声音克隆 */}
        <div>
          <h3 className="text-sm font-semibold text-purple-700 mb-2.5">声音复刻</h3>
          <div className="glass-card p-4">
            <p className="text-xs text-purple-500 mb-3">
              上传 15-30 秒清晰音频，生成专属克隆音色
            </p>
            
            {/* 授权声明 */}
            <label className="flex items-start gap-2 mb-4 cursor-pointer">
              <input
                type="checkbox"
                checked={consentAgreed}
                onChange={(e) => setConsentAgreed(e.target.checked)}
                className="mt-0.5 w-4 h-4 text-purple-500 rounded focus:ring-purple-400"
              />
              <span className="text-xs text-gray-600 leading-relaxed">
                我确认上传的音频为本人嗓音，或我已获得权利人的明确授权；我理解使用未经授权的音频（含名人/影视/动漫角色等）所产生的一切法律责任由我本人承担，与平台无关。
              </span>
            </label>
            
            {/* 音频时长提示 */}
            {audioDuration !== null && (
              <div className={`mt-2 px-3 py-2 rounded-xl text-xs ${
                audioDuration >= 15 && audioDuration <= 30 
                  ? 'bg-green-50 text-green-600 border border-green-200' 
                  : 'bg-red-50 text-red-600 border border-red-200'
              }`}>
                {audioDuration < 15 && `⚠️ 音频时长 ${audioDuration.toFixed(1)} 秒，太短了，请上传 15-30 秒的音频`}
                {audioDuration > 30 && `⚠️ 音频时长 ${audioDuration.toFixed(1)} 秒，请控制在 30 秒内`}
                {audioDuration >= 15 && audioDuration <= 30 && `✅ 音频时长 ${audioDuration.toFixed(1)} 秒，符合要求`}
              </div>
            )}
            
            {/* 上传区域 */}
            <label 
              className={`w-full flex flex-col items-center justify-center py-6 border-2 border-dashed rounded-xl cursor-pointer transition-colors mt-4 ${
                consentAgreed && (audioDuration === null || (audioDuration >= 15 && audioDuration <= 30))
                  ? 'border-purple-200 hover:border-purple-400' 
                  : 'border-gray-200 cursor-not-allowed opacity-50'
              }`}
            >
              <input
                type="file"
                accept="audio/*"
                className="hidden"
                disabled={!consentAgreed || (audioDuration !== null && (audioDuration < 15 || audioDuration > 30))}
                onChange={async e => {
                  const file = e.target.files?.[0]
                  if (!file) return
                  
                  const audio = new Audio(URL.createObjectURL(file))
                  audio.onloadedmetadata = async () => {
                    const duration = audio.duration
                    setAudioDuration(duration)
                    URL.revokeObjectURL(audio.src)
                    
                    if (duration < 15) {
                      showToast('参考音频太短，请上传 15-30 秒', 'error')
                      return
                    }
                    if (duration > 30) {
                      showToast('请控制在 30 秒内', 'error')
                      return
                    }
                    
                    setUploadedAudioName(file.name)
                    try {
                      await apiVoice.upload(id!, file, consentAgreed)
                      showToast('已上传，可开始克隆', 'success')
                      setCloneStatus('not_cloned')
                    } catch (err: any) {
                      showToast(err?.message || '上传失败', 'error')
                    }
                  }
                }}
              />
              <span className="text-3xl text-purple-300 mb-2">🎵</span>
              <span className="text-sm text-purple-600 font-medium">点击选择音频文件</span>
              <span className="text-xs text-purple-400 mt-1">支持 MP3、WAV 等格式，建议 15-30 秒</span>
            </label>
            
            {uploadedAudioName && (
              <div className="mt-3 flex items-center gap-2 text-sm text-purple-600">
                <span>📎</span>
                <span className="truncate">{uploadedAudioName}</span>
                {audioDuration !== null && (
                  <span className="text-xs text-gray-400">({audioDuration.toFixed(1)}秒)</span>
                )}
              </div>
            )}
            
            {/* 参考文本输入 + 开始克隆 */}
            {uploadedAudioName && cloneStatus === 'not_cloned' && (
              <div className="mt-4 space-y-3">
                <input
                  type="text"
                  placeholder="参考音频里念的话（选填，填了克隆更准）"
                  value={promptText}
                  onChange={(e) => setPromptText(e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-purple-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-purple-300"
                />
                <button
                  onClick={async () => {
                    try {
                      setCloneStatus('cloning')
                      await apiVoice.cloneStart(id!, promptText)
                      showToast('克隆就绪', 'success')
                      setCloneStatus('ready')
                    } catch (err: any) {
                      showToast(err?.message || '克隆失败', 'error')
                      setCloneStatus('failed')
                    }
                  }}
                  className="w-full py-2 bg-purple-500 text-white text-sm rounded-xl hover:bg-purple-600 transition-colors"
                >
                  开始克隆
                </button>
              </div>
            )}
            
            {/* 克隆中状态 */}
            {cloneStatus === 'cloning' && (
              <div className="mt-4 px-3 py-2 bg-yellow-50 border border-yellow-200 rounded-xl text-xs text-yellow-600">
                克隆中...
              </div>
            )}
            {cloneStatus === 'ready' && (
              <div className="mt-4 space-y-3">
                <div className="px-3 py-2 bg-green-50 border border-green-200 rounded-xl text-xs text-green-600 flex items-center gap-2">
                  <span>✅</span>
                  <span>克隆就绪</span>
                </div>
                <button
                  onClick={async () => {
                    try {
                      const result = await apiVoice.generate(
                        id!,
                        '你好呀，我是你的专属灵偶，以后我就用这个声音陪着你啦。',
                      )
                      if (result.audio_path) {
                        const audio = new Audio(`/api/voice/play?path=${encodeURIComponent(result.audio_path)}`)
                        audio.play()
                      }
                    } catch (err: any) {
                      showToast(err?.message || '试听失败', 'error')
                    }
                  }}
                  className="w-full py-2 bg-green-500 text-white text-sm rounded-xl hover:bg-green-600 transition-colors"
                >
                  🔊 试听克隆音色
                </button>
                <p className="text-xs text-gray-400 text-center">已设为该灵偶的声音</p>
              </div>
            )}
            
            {/* 失败状态 */}
            {cloneStatus === 'failed' && (
              <div className="mt-4 space-y-3">
                <div className="px-3 py-2 bg-red-50 border border-red-200 rounded-xl text-xs text-red-600">
                  克隆失败，请重试
                </div>
                <button
                  onClick={() => setCloneStatus('not_cloned')}
                  className="w-full py-2 bg-purple-500 text-white text-sm rounded-xl hover:bg-purple-600 transition-colors"
                >
                  重新克隆
                </button>
              </div>
            )}
          </div>
        </div>

        {/* 触摸反应 */}
        <div>
          <h3 className="text-sm font-semibold text-purple-700 mb-2.5">触摸反应</h3>
          <div className="space-y-2">
            {TOUCH_REACTIONS_TEMPLATE.map(t => (
              <div key={t.key} className="glass-card p-3">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xl">{t.icon}</span>
                  <span className="font-medium text-purple-900 text-sm flex-1">{t.label}</span>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={touchReactions[t.key]?.reply || ''}
                    onChange={e => setTouchReactions({ ...touchReactions, [t.key]: { ...touchReactions[t.key], reply: e.target.value } })}
                    className="flex-1 px-3 py-2 bg-white/70 border border-purple-100 rounded-xl text-sm text-purple-900 focus:outline-none focus:ring-2 focus:ring-purple-300"
                  />
                  <button
                    onClick={() => openTouchEditModal(t.key)}
                    className="w-8 h-8 rounded-full bg-white text-purple-600 flex items-center justify-center shadow-sm border border-purple-100"
                  >✎</button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 灵魂档案 - 口头禅 */}
        <div>
          <h3 className="text-sm font-semibold text-purple-700 mb-2.5">口头禅</h3>
          <div className="glass-card p-4">
            <div className="flex flex-wrap gap-2">
              {catchphrases.map((phrase, i) => (
                <div key={i} className="flex items-center gap-1">
                  <input
                    type="text"
                    value={phrase}
                    onChange={(e) => {
                      const newPhrases = [...catchphrases]
                      newPhrases[i] = e.target.value
                      setCatchphrases(newPhrases)
                    }}
                    className="px-3 py-1.5 bg-white/60 border border-purple-200 rounded-full text-sm text-purple-800 focus:outline-none focus:ring-1 focus:ring-purple-300"
                  />
                  <button onClick={() => {
                    setCatchphrases(catchphrases.filter((_, idx) => idx !== i))
                  }} className="text-purple-400 text-xs">×</button>
                </div>
              ))}
            </div>
            <button onClick={() => setCatchphrases([...catchphrases, ''])}
              className="w-full py-2 bg-purple-100 text-purple-600 rounded-xl text-sm font-medium hover:bg-purple-200 transition-colors mt-2">
              + 新增口头禅
            </button>
          </div>
        </div>

        {/* 灵魂档案 - 标志台词 */}
        <div>
          <h3 className="text-sm font-semibold text-purple-700 mb-2.5">标志台词</h3>
          <div className="glass-card p-4">
            <div className="flex flex-wrap gap-2">
              {signatureLines.map((line, i) => (
                <div key={i} className="flex items-center gap-1">
                  <input
                    type="text"
                    value={line}
                    onChange={(e) => {
                      const newLines = [...signatureLines]
                      newLines[i] = e.target.value
                      setSignatureLines(newLines)
                    }}
                    className="px-3 py-1.5 bg-white/60 border border-purple-200 rounded-full text-sm text-purple-800 focus:outline-none focus:ring-1 focus:ring-purple-300"
                  />
                  <button onClick={() => {
                    setSignatureLines(signatureLines.filter((_, idx) => idx !== i))
                  }} className="text-purple-400 text-xs">×</button>
                </div>
              ))}
            </div>
            <button onClick={() => setSignatureLines([...signatureLines, ''])}
              className="w-full py-2 bg-purple-100 text-purple-600 rounded-xl text-sm font-medium hover:bg-purple-200 transition-colors mt-2">
              + 新增标志台词
            </button>
          </div>
        </div>

        {/* 灵魂档案 - 禁忌话题 */}
        <div>
          <h3 className="text-sm font-semibold text-purple-700 mb-2.5">禁忌话题</h3>
          <div className="glass-card p-4">
            <div className="flex flex-wrap gap-2">
              {taboos.map((taboo, i) => (
                <div key={i} className="flex items-center gap-1">
                  <input
                    type="text"
                    value={taboo}
                    onChange={(e) => {
                      const newTaboos = [...taboos]
                      newTaboos[i] = e.target.value
                      setTaboos(newTaboos)
                    }}
                    className="px-3 py-1.5 bg-red-50 border border-red-200 rounded-full text-sm text-red-700 focus:outline-none focus:ring-1 focus:ring-red-300"
                  />
                  <button onClick={() => {
                    setTaboos(taboos.filter((_, idx) => idx !== i))
                  }} className="text-purple-400 text-xs">×</button>
                </div>
              ))}
            </div>
            <button onClick={() => setTaboos([...taboos, ''])}
              className="w-full py-2 bg-red-100 text-red-600 rounded-xl text-sm font-medium hover:bg-red-200 transition-colors mt-2">
              + 新增禁忌话题
            </button>
          </div>
        </div>

        {/* 灵魂档案 - 关系网/记忆 */}
        <div>
          <h3 className="text-sm font-semibold text-purple-700 mb-2.5">关系网/记忆</h3>
          <div className="glass-card p-4">
            <div className="space-y-2">
              {Object.entries(relationships || {}).map(([relation, target], i) => (
                <div key={i} className="flex items-center gap-2 bg-white/60 rounded-xl px-3 py-2">
                  <input
                    type="text"
                    value={relation}
                    onChange={(e) => {
                      const newRelationships = { ...relationships }
                      delete newRelationships[relation]
                      newRelationships[e.target.value] = target
                      setRelationships(newRelationships)
                    }}
                    className="flex-1 px-2 py-1.5 bg-transparent border border-purple-100 rounded-lg text-sm text-purple-700 focus:outline-none focus:ring-1 focus:ring-purple-300"
                    placeholder="关系"
                  />
                  <span className="text-purple-400 text-sm">→</span>
                  <input
                    type="text"
                    value={target}
                    onChange={(e) => {
                      const newRelationships = { ...relationships }
                      newRelationships[relation] = e.target.value
                      setRelationships(newRelationships)
                    }}
                    className="flex-1 px-2 py-1.5 bg-transparent border border-purple-100 rounded-lg text-sm text-purple-700 focus:outline-none focus:ring-1 focus:ring-purple-300"
                    placeholder="对象"
                  />
                  <button onClick={() => {
                    const newRelationships = { ...relationships }
                    delete newRelationships[relation]
                    setRelationships(newRelationships)
                  }} className="w-6 h-6 rounded-full bg-red-100 text-red-500 flex items-center justify-center text-xs">×</button>
                </div>
              ))}
              <button onClick={() => {
                const newRelationships = { ...relationships, [`新关系${Object.keys(relationships || {}).length + 1}`]: '' }
                setRelationships(newRelationships)
              }} className="w-full py-2 bg-purple-100 text-purple-600 rounded-xl text-sm font-medium hover:bg-purple-200 transition-colors">
                + 新增关系
              </button>
            </div>
          </div>
        </div>

        {/* 灵魂档案 - 性格特质 */}
        <div>
          <h3 className="text-sm font-semibold text-purple-700 mb-2.5">性格特质</h3>
          <div className="glass-card p-4">
            <div className="flex flex-wrap gap-2">
              {traits.map((trait, i) => (
                <div key={i} className="flex items-center gap-1">
                  <input
                    type="text"
                    value={trait}
                    onChange={(e) => {
                      const newTraits = [...traits]
                      newTraits[i] = e.target.value
                      setTraits(newTraits)
                    }}
                    className="px-3 py-1.5 bg-white/60 border border-purple-200 rounded-full text-sm text-purple-800 focus:outline-none focus:ring-1 focus:ring-purple-300"
                  />
                  <button onClick={() => {
                    const newTraits = traits.filter((_, idx) => idx !== i)
                    setTraits(newTraits)
                  }} className="text-purple-400 text-xs">×</button>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 灵魂档案 - 价值观 */}
        <div>
          <h3 className="text-sm font-semibold text-purple-700 mb-2.5">价值观</h3>
          <div className="glass-card p-4">
            <div className="flex flex-wrap gap-2">
              {values.map((value, i) => (
                <div key={i} className="flex items-center gap-1">
                  <input
                    type="text"
                    value={value}
                    onChange={(e) => {
                      const newValues = [...values]
                      newValues[i] = e.target.value
                      setValues(newValues)
                    }}
                    className="px-3 py-1.5 bg-blue-50 border border-blue-200 rounded-full text-sm text-blue-700 focus:outline-none focus:ring-1 focus:ring-blue-300"
                  />
                  <button onClick={() => {
                    const newValues = values.filter((_, idx) => idx !== i)
                    setValues(newValues)
                  }} className="text-purple-400 text-xs">×</button>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 灵魂档案 - 知识边界（只读） */}
        <div>
          <h3 className="text-sm font-semibold text-purple-700 mb-2.5">懂/不懂边界</h3>
          <div className="glass-card p-4">
            <div className="space-y-3">
              <div>
                <span className="text-xs text-green-600 font-medium">懂这些</span>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {knowledgeBounds.knows?.map((know, i) => (
                    <span key={i} className="chip bg-green-50 text-green-600 border-green-200">{know}</span>
                  ))}
                </div>
              </div>
              <div>
                <span className="text-xs text-orange-600 font-medium">不懂这些</span>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {knowledgeBounds.unknowns?.map((unknown, i) => (
                    <span key={i} className="chip bg-orange-50 text-orange-600 border-orange-200">{unknown}</span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 底部保存 */}
      <div className="fixed-action-bar">
        <div className="fixed-action-bar__inner space-y-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className="btn-soul w-full flex items-center justify-center gap-2"
          >
            {saving ? '保存中…' : '保存修改'}
          </button>
          <button
            onClick={() => setShowDeleteConfirm(true)}
            disabled={deleting}
            className="w-full py-2.5 text-red-500 text-sm hover:bg-red-50 rounded-xl transition-colors"
          >
            删除灵偶
          </button>
          <button
            onClick={() => navigate(`/soul/${id}`)}
            className="text-purple-500 text-sm w-full py-2"
          >
            取消
          </button>
        </div>
      </div>

      {/* 删除确认弹窗 */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowDeleteConfirm(false)} />
          <div className="glass-card p-6 w-full max-w-sm relative z-10">
            <h3 className="text-lg font-bold text-purple-900 mb-2">确认删除？</h3>
            <p className="text-sm text-purple-600 mb-5">
              删除后「{figure?.name || '这个灵偶'}」的所有档案、对话记录和关系进度都会永久消失，无法恢复。
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="flex-1 py-2.5 bg-purple-100 text-purple-700 rounded-xl text-sm font-medium"
              >
                再想想
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="flex-1 py-2.5 bg-red-500 text-white rounded-xl text-sm font-medium disabled:opacity-50"
              >
                {deleting ? '删除中…' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 触摸编辑弹窗 */}
      {showTouchEditModal && editingTouchKey && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowTouchEditModal(false)} />
          <div className="relative w-full max-w-sm animate-fade-in overflow-hidden rounded-[30px] bg-white/92 p-6 shadow-soul-lg ring-1 ring-white/80">
            <h3 className="text-lg font-bold text-soul-gradient text-center mb-2">
              {TOUCH_REACTIONS_TEMPLATE.find(t => t.key === editingTouchKey)?.label}
            </h3>
            <textarea
              value={editingTouchReply}
              onChange={e => setEditingTouchReply(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 bg-white/60 border border-purple-100 rounded-xl text-sm text-purple-900 focus:outline-none focus:ring-2 focus:ring-purple-300 resize-none mb-4"
            />
            <div className="flex gap-3">
              <button onClick={() => setShowTouchEditModal(false)} className="flex-1 py-2.5 bg-white/60 text-purple-600 rounded-xl text-sm font-medium border border-purple-100">
                取消
              </button>
              <button onClick={saveTouchEdit} className="flex-1 py-2.5 bg-gradient-to-r from-purple-500 to-pink-500 text-white rounded-xl text-sm font-medium">
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
