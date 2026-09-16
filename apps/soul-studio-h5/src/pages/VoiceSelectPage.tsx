import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiVoice, apiFigures } from '../services/api'
import StarField from '../components/StarField'
import PageHeader from '../components/PageHeader'
import LiquidGlassPanel from '../components/LiquidGlassPanel'
import SoulFigureStage from '../components/SoulFigureStage'
import { useVoicePreview } from '../hooks/useVoicePreview'

const TEST_PHRASES = [
  '很高兴又见到你',
  '今天心情怎么样？',
  '抱抱～不哭不哭',
]

interface Speaker {
  speaker_id: string
  name: string
  description?: string
}

export default function VoiceSelectPage() {
  const navigate = useNavigate()
  const [figures, setFigures] = useState<any[]>([])
  const [selectedFigId, setSelectedFigId] = useState('')
  const [candidateSpeakerId, setCandidateSpeakerId] = useState('')
  const [speakerInfo, setSpeakerInfo] = useState<any>(null)
  const [previewText, setPreviewText] = useState(TEST_PHRASES[0])
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const {
    snapshot: previewSnapshot,
    preview,
    stop: stopPreview,
  } = useVoicePreview()

  const speakersList: Speaker[] = speakerInfo?.speakers || []
  const selectedFig = figures.find(f => f.figure_id === selectedFigId)
  const currentSpeaker = selectedFig?.voice_profile?.speaker || ''
  const currentSpeakerMeta = speakersList.find(sp => sp.speaker_id === currentSpeaker)
  const currentPreviewKey = selectedFigId ? `current-${selectedFigId}` : ''
  const previewBusy = ['synthesizing', 'transferred', 'decoded', 'playing']
    .includes(previewSnapshot.status)

  useEffect(() => {
    apiFigures.list()
      .then(figs => {
        setFigures(figs)
        if (figs[0]) setSelectedFigId(prev => prev || figs[0].figure_id)
      })
      .catch(() => {})
    apiVoice.listSpeakers().then(setSpeakerInfo).catch(() => {})
  }, [])

  useEffect(() => {
    stopPreview()
    setCandidateSpeakerId(currentSpeaker)
  }, [currentSpeaker, selectedFigId, stopPreview])

  useEffect(() => {
    if (previewSnapshot.status === 'error') {
      setMsg(`试听失败：${previewSnapshot.error}`)
    }
  }, [previewSnapshot.error, previewSnapshot.status])

  async function handlePreview(speakerId: string, targetKey = speakerId) {
    if ((!speakerId && !selectedFigId) || !previewText.trim()) {
      setMsg('请先选择要试听的声线')
      return
    }
    setMsg('')
    await preview({
      figure_id: selectedFigId || undefined,
      speaker: speakerId || undefined,
      text: previewText.trim(),
    }, targetKey)
  }

  async function handleDesign() {
    if (!selectedFigId || !candidateSpeakerId) return
    setSaving(true)
    setMsg('')
    try {
      await apiVoice.design(selectedFigId, candidateSpeakerId)
      const saved = await apiFigures.get(selectedFigId)
      if (saved.voice_profile?.speaker !== candidateSpeakerId) {
        throw new Error('保存后的声线与所选声线不一致')
      }
      setFigures(current => current.map(figure => (
        figure.figure_id === saved.figure_id ? saved : figure
      )))
      setMsg('声线已保存并确认')
    } catch (e: any) {
      setMsg('切换失败: ' + (e.message || ''))
    } finally {
      setSaving(false)
    }
  }

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
                  ? `${currentSpeakerMeta.name}${currentSpeakerMeta.description ? ` · ${currentSpeakerMeta.description}` : ''}`
                  : currentSpeaker
                    ? '已配置专属声线'
                    : '还未设置专属声线'}
              </p>
              <button
                onClick={() => handlePreview('', currentPreviewKey)}
                disabled={previewBusy || !previewText.trim()}
                className="mt-3 rounded-full bg-gradient-to-r from-purple-500 to-pink-500 px-4 py-2 text-xs font-black text-white shadow-lg shadow-purple-300/35 disabled:opacity-45"
              >
                {previewBusy && previewSnapshot.targetKey === currentPreviewKey
                  ? '播放中...'
                  : '试听当前声线'}
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
              onClick={() => handlePreview(candidateSpeakerId)}
              disabled={previewBusy || !previewText.trim() || !candidateSpeakerId}
              className="btn-soul mt-3 w-full text-sm disabled:opacity-40"
            >
              {previewBusy ? '正在准备并播放…' : '播放所选声线'}
            </button>
            {candidateSpeakerId && candidateSpeakerId !== currentSpeaker && (
              <button
                onClick={handleDesign}
                disabled={saving || previewBusy}
                className="mt-2 w-full rounded-2xl bg-purple-100 py-2.5 text-sm font-black text-purple-700 disabled:opacity-40"
              >
                {saving ? '正在保存…' : '确认选用这条声线'}
              </button>
            )}
            {previewSnapshot.status !== 'idle' && (
              <p aria-live="polite" className="mt-2 text-center text-xs font-semibold text-purple-500">
                {previewSnapshot.status === 'synthesizing' && '正在生成试听音频'}
                {previewSnapshot.status === 'transferred' && '音频已传输'}
                {previewSnapshot.status === 'decoded' && '音频已解码'}
                {previewSnapshot.status === 'playing' && '正在当前设备播放'}
                {previewSnapshot.status === 'completed' && '试听播放完成'}
                {previewSnapshot.status === 'error' && previewSnapshot.error}
              </p>
            )}
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
            <div className="max-h-[520px] space-y-2.5 overflow-y-auto pr-1">
              {speakersList.map(sp => {
                const current = currentSpeaker === sp.speaker_id
                const candidate = candidateSpeakerId === sp.speaker_id
                return (
                  <div
                    key={sp.speaker_id}
                    className={`rounded-[22px] p-3 ring-1 transition-all ${
                      candidate
                        ? 'bg-gradient-to-br from-purple-50 to-pink-50 ring-purple-300 shadow-sm'
                        : 'bg-white/65 ring-purple-100 hover:bg-purple-50/70'
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-lg text-white shadow-lg ${
                        candidate ? 'bg-gradient-to-br from-purple-500 to-pink-500' : 'bg-gradient-to-br from-purple-300 to-indigo-300'
                      }`}>
                        🎙
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-black text-purple-950">{sp.name}</p>
                        <p className="mt-0.5 text-xs text-purple-500">{sp.description}</p>
                        <p className="mt-1 truncate text-[10px] font-semibold text-purple-300">
                          云端情感声线
                        </p>
                      </div>
                    </div>
                    <div className="mt-3 flex gap-2">
                      <button
                        onClick={() => handlePreview(sp.speaker_id)}
                        disabled={previewBusy || saving}
                        className="flex-1 rounded-full bg-white/80 px-3 py-1.5 text-xs font-bold text-purple-600 ring-1 ring-purple-100 disabled:opacity-40"
                      >
                        {previewBusy && previewSnapshot.targetKey === sp.speaker_id
                          ? '播放中'
                          : '试听'}
                      </button>
                      {candidate ? (
                        <span className="rounded-full bg-gradient-to-r from-purple-500 to-pink-500 px-3 py-1.5 text-xs font-bold text-white">
                          {current ? '已选用' : '待确认'}
                        </span>
                      ) : (
                        <button
                          onClick={() => {
                            stopPreview()
                            setCandidateSpeakerId(sp.speaker_id)
                            setMsg('')
                          }}
                          disabled={saving}
                          className="rounded-full bg-purple-100 px-3 py-1.5 text-xs font-bold text-purple-600 disabled:opacity-40"
                        >
                          选择
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
            云端实时合成暂不可用，将播放该声线的官方样本
          </p>
        )}
      </div>
    </div>
  )
}
