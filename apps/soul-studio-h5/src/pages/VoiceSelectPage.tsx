import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiVoice, apiFigures } from '../services/api'
import StarField from '../components/StarField'
import PageHeader from '../components/PageHeader'
import LiquidGlassPanel from '../components/LiquidGlassPanel'
import SoulFigureStage from '../components/SoulFigureStage'

const TEST_PHRASES = [
  '主人，欢迎回来呀',
  '今天心情怎么样？',
  '抱抱～不哭不哭',
]

interface Speaker {
  speaker_id: string
  name: string
  description: string
  engine: string
}

export default function VoiceSelectPage() {
  const navigate = useNavigate()
  const [figures, setFigures] = useState<any[]>([])
  const [selectedFigId, setSelectedFigId] = useState('')
  const [speakerInfo, setSpeakerInfo] = useState<any>(null)
  const [previewText, setPreviewText] = useState(TEST_PHRASES[0])
  const [playing, setPlaying] = useState(false)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    apiFigures.list()
      .then(figs => {
        setFigures(figs)
        if (figs[0]) setSelectedFigId(prev => prev || figs[0].figure_id)
      })
      .catch(() => {})
    apiVoice.listSpeakers().then(setSpeakerInfo).catch(() => {})
  }, [])

  async function handlePreview() {
    if (!selectedFigId || !previewText.trim()) return
    setPlaying(true)
    try {
      await apiVoice.generate(selectedFigId, previewText.trim())
    } catch (e: any) {
      setMsg('播放失败: ' + (e.message || ''))
    } finally {
      setTimeout(() => setPlaying(false), 1500)
    }
  }

  async function handleDesign(speakerId: string) {
    if (!selectedFigId) return
    setSaving(true)
    try {
      await apiVoice.design(selectedFigId, speakerId)
      setMsg('音色切换成功！')
    } catch (e: any) {
      setMsg('切换失败: ' + (e.message || ''))
    } finally {
      setSaving(false)
    }
  }

  const speakersList: Speaker[] = speakerInfo?.speakers || []
  const selectedFig = figures.find(f => f.figure_id === selectedFigId)
  const currentSpeaker = selectedFig?.voice_profile?.speaker || ''
  const currentSpeakerMeta = speakersList.find(sp => sp.speaker_id === currentSpeaker)

  return (
    <div className="min-h-screen bg-castle relative overflow-hidden">
      <StarField count={18} />
      <div className="pointer-events-none absolute -top-24 right-0 h-64 w-64 rounded-full bg-violet-200/24 blur-3xl" />

      <PageHeader
        title="音色实验室"
        subtitle="选择灵偶 · 试听火山情感音色"
        onBack={() => navigate(-1)}
      />

      <div className="relative z-10 mx-auto flex w-full max-w-lg flex-col gap-4 px-4 pb-28">
        <LiquidGlassPanel
          contentClassName="liquid-brand-surface p-5 text-white"
          radius={30}
          variant="hero"
        >
            <p className="text-[10px] font-bold tracking-[0.28em] text-white/65">VOICE DESIGN</p>
            <h2 className="mt-2 text-2xl font-black">给灵偶换一条灵魂声线</h2>
            <p className="mt-2 text-xs leading-relaxed text-white/75">
              为当前灵偶选择更贴合性格的声音，试听后再决定是否选用。
            </p>
        </LiquidGlassPanel>

        {selectedFig && (
          <section className="voice-current-card">
            <div className="voice-current-card__stage">
              <SoulFigureStage figure={selectedFig} className="voice-current-card__figure" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-black uppercase tracking-[0.2em] text-purple-400">当前声线</p>
              <h3 className="mt-1 truncate text-xl font-black text-purple-950">{selectedFig.name}</h3>
              <p className="mt-1 truncate text-xs font-semibold text-purple-500">
                {currentSpeakerMeta
                  ? `${currentSpeakerMeta.name} · ${currentSpeakerMeta.description}`
                  : currentSpeaker
                    ? '已配置专属声线'
                    : '还未设置专属声线'}
              </p>
              <button
                onClick={handlePreview}
                disabled={playing || !previewText.trim()}
                className="mt-3 rounded-full bg-gradient-to-r from-purple-500 to-pink-500 px-4 py-2 text-xs font-black text-white shadow-lg shadow-purple-300/35 disabled:opacity-45"
              >
                {playing ? '播放中...' : '试听当前台词'}
              </button>
            </div>
          </section>
        )}

        {/* Figure selector */}
        <section className="glass-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <p className="text-sm font-black text-purple-900">选择灵偶</p>
              <p className="text-[11px] font-medium text-purple-400">先选择角色，再调整声线</p>
            </div>
            <span className="rounded-full bg-white/70 px-2.5 py-1 text-[10px] font-bold text-purple-500 ring-1 ring-white/70">
              {figures.length} 个
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {figures.map(fig => (
              <button
                key={fig.figure_id}
                onClick={() => setSelectedFigId(fig.figure_id)}
                className={`rounded-2xl px-3 py-2 text-sm font-bold transition-all ${
                  selectedFigId === fig.figure_id
                    ? 'bg-gradient-to-r from-purple-500 to-pink-500 text-white shadow-lg shadow-purple-300/35'
                    : 'bg-white/70 text-purple-600 ring-1 ring-purple-100 hover:bg-purple-50'
                }`}
              >
                {fig.name}
              </button>
            ))}
          </div>
          {!selectedFig && (
            <div className="mt-3 rounded-2xl bg-white/60 p-3 text-xs text-purple-400 ring-1 ring-white/70">
              请选择一个灵偶后试听声线
            </div>
          )}
        </section>

        {/* Preview text input */}
        {selectedFigId && (
          <section className="glass-card p-4">
            <p className="mb-3 text-sm font-black text-purple-900">试听台词</p>
            <div className="mb-3 flex flex-wrap gap-2">
              {TEST_PHRASES.map(phrase => (
                <button
                  key={phrase}
                  onClick={() => setPreviewText(phrase)}
                  className={`rounded-full px-3 py-1.5 text-xs font-semibold ring-1 transition-all ${
                    previewText === phrase
                      ? 'bg-purple-100 text-purple-700 ring-purple-200'
                      : 'bg-white/70 text-purple-400 ring-purple-100 hover:text-purple-600'
                  }`}
                >
                  {phrase}
                </button>
              ))}
            </div>
            <textarea
              value={previewText}
              onChange={e => setPreviewText(e.target.value)}
              className="w-full resize-none rounded-2xl border border-purple-100 bg-white/65 px-3 py-2 text-sm text-purple-900 placeholder-purple-300 focus:outline-none focus:ring-2 focus:ring-purple-300"
              rows={2}
              placeholder="输入自定义预览文本..."
            />
            <button
              onClick={handlePreview}
              disabled={playing || !previewText.trim()}
              className="btn-soul mt-3 w-full text-sm disabled:opacity-40"
            >
              {playing ? '🔊 播放中...' : '🎵 播放预览'}
            </button>
          </section>
        )}

        {/* Speaker list */}
        {selectedFigId && (
          <section className="glass-card p-4">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-black text-purple-900">可选音色</p>
              <span className="rounded-full bg-purple-50 px-2.5 py-1 text-[10px] font-bold text-purple-500">
                {speakersList.length} 条
              </span>
            </div>
            <div className="space-y-2.5">
              {speakersList.map(sp => {
                const current = currentSpeaker === sp.speaker_id
                return (
                  <div
                    key={sp.speaker_id}
                    className={`cursor-pointer rounded-[22px] p-3 ring-1 transition-all ${
                      current
                        ? 'bg-gradient-to-br from-purple-50 to-pink-50 ring-purple-300 shadow-sm'
                        : 'bg-white/65 ring-purple-100 hover:bg-purple-50/70'
                    }`}
                    onClick={() => !saving && handleDesign(sp.speaker_id)}
                  >
                    <div className="flex items-start gap-3">
                      <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-lg text-white shadow-lg ${
                        current ? 'bg-gradient-to-br from-purple-500 to-pink-500' : 'bg-gradient-to-br from-purple-300 to-indigo-300'
                      }`}>
                        🎙
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-black text-purple-950">{sp.name}</p>
                        <p className="mt-0.5 text-xs text-purple-500">{sp.description}</p>
                        <p className="mt-1 truncate text-[10px] font-semibold text-purple-300">
                          {sp.engine ? '云端情感声线' : '系统声线'}
                        </p>
                      </div>
                    </div>
                    <div className="mt-3 flex gap-2">
                      <button
                        onClick={(e) => { e.stopPropagation(); handlePreview() }}
                        disabled={playing}
                        className="flex-1 rounded-full bg-white/80 px-3 py-1.5 text-xs font-bold text-purple-600 ring-1 ring-purple-100 disabled:opacity-40"
                      >
                        {playing ? '播放中' : '试听'}
                      </button>
                      {current ? (
                        <span className="rounded-full bg-gradient-to-r from-purple-500 to-pink-500 px-3 py-1.5 text-xs font-bold text-white">
                          已选用
                        </span>
                      ) : (
                        <button
                          disabled={saving}
                          className="rounded-full bg-purple-100 px-3 py-1.5 text-xs font-bold text-purple-600 disabled:opacity-40"
                        >
                          选用
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        )}

        {msg && (
          <p className={`rounded-2xl px-4 py-3 text-center text-sm font-semibold ${
            msg.includes('失败') ? 'bg-red-50 text-red-500' : 'bg-green-50 text-green-600'
          }`}>
            {msg}
          </p>
        )}

        {speakerInfo && !speakerInfo.available && (
          <p className="rounded-2xl bg-orange-50 px-4 py-3 text-center text-xs font-semibold text-orange-500">
            云端音色服务暂未配置，当前仅支持系统试听
          </p>
        )}
      </div>
    </div>
  )
}
