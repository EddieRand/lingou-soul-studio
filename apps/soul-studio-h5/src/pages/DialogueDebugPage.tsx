import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { apiBases, apiDialogue, type BaseDetail } from '../services/api'
import { useVoiceCall } from '../hooks/useVoiceCall'
import type { VoiceServerMessage } from '../services/voiceCallController'
import StarField from '../components/StarField'
import PageHeader from '../components/PageHeader'
import LiquidGlassPanel from '../components/LiquidGlassPanel'
import SoulFigureStage from '../components/SoulFigureStage'

interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  brainMode?: string
  streaming?: boolean
  turnId?: string
}

export default function DialogueDebugPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const requestedFigureId = searchParams.get('figure_id')
  const [baseId, setBaseId] = useState<string | null>(null)
  const [baseData, setBaseData] = useState<BaseDetail | null>(null)
  const [dialogueState, setDialogueState] = useState('idle')

  const [chatInput, setChatInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const chatScrollRef = useRef<HTMLDivElement>(null)

  const [asrAvailable, setAsrAvailable] = useState(false)
  const activeBaseIdRef = useRef<string | null>(null)
  const activeFigureIdRef = useRef<string | null>(null)
  const loadAttemptRef = useRef(0)

  const handleVoiceServerMessage = useCallback((data: VoiceServerMessage) => {
    const turnId = data.turn_id
    switch (data.type) {
      case 'final':
        if (!data.text) return
        setMessages(current => {
          if (
            turnId
            && current.some(message => (
              message.role === 'user' && message.turnId === turnId
            ))
          ) return current
          return [...current, { role: 'user', text: data.text || '', turnId }]
        })
        break
      case 'reply_chunk':
        if (!data.text) return
        setMessages(current => {
          const existingIndex = turnId
            ? current.findIndex(message => (
              message.role === 'assistant' && message.turnId === turnId
            ))
            : -1
          if (existingIndex >= 0) {
            const updated = [...current]
            const existing = updated[existingIndex]
            updated[existingIndex] = {
              ...existing,
              text: existing.text + data.text,
              streaming: true,
            }
            return updated
          }
          return [
            ...current,
            {
              role: 'assistant',
              text: data.text || '',
              streaming: true,
              turnId,
            },
          ]
        })
        break
      case 'reply':
        setMessages(current => {
          const existingIndex = turnId
            ? current.findIndex(message => (
              message.role === 'assistant' && message.turnId === turnId
            ))
            : -1
          if (existingIndex >= 0) {
            const updated = [...current]
            const existing = updated[existingIndex]
            updated[existingIndex] = {
              ...existing,
              text: data.reply || existing.text,
              streaming: false,
              brainMode: data.brain_mode,
            }
            return updated
          }
          if (!data.reply) return current
          return [
            ...current,
            {
              role: 'assistant',
              text: data.reply,
              brainMode: data.brain_mode,
              turnId,
            },
          ]
        })
        break
      case 'turn_cancelled':
        if (!turnId) return
        setMessages(current => current.map(message => (
          message.role === 'assistant' && message.turnId === turnId
            ? { ...message, streaming: false }
            : message
        )))
        break
    }
  }, [])

  const {
    snapshot: voiceSnapshot,
    start: startManagedCall,
    stop: stopManagedCall,
  } = useVoiceCall({ onServerMessage: handleVoiceServerMessage })
  const isInCall = voiceSnapshot.active
  const voiceHint = voiceSnapshot.hint
  const asrError = voiceSnapshot.error
  const voiceCallState = voiceSnapshot.status === 'speaking'
    ? 'speaking'
    : voiceSnapshot.status === 'listening'
      ? 'listening'
      : 'connecting'

  const loadData = useCallback(async () => {
    const loadAttempt = ++loadAttemptRef.current
    try {
      const bases = await apiBases.list()
      if (loadAttempt !== loadAttemptRef.current) return
      const currentBase = bases[0] || null
      const currentBaseId = currentBase?.base.base_id || null

      if (activeBaseIdRef.current !== currentBaseId) {
        stopManagedCall('base_changed')
        activeBaseIdRef.current = currentBaseId
        activeFigureIdRef.current = null
        setMessages([])
      }
      setBaseId(currentBaseId)
      setBaseData(currentBase)

      if (!currentBase || !currentBaseId) {
        setDialogueState('idle')
        return
      }

      const currentFigureId = currentBase.figure?.figure_id || null
      if (
        requestedFigureId
        && currentFigureId
        && requestedFigureId !== currentFigureId
      ) {
        navigate('/home', { replace: true })
        return
      }
      if (
        activeFigureIdRef.current
        && activeFigureIdRef.current !== currentFigureId
      ) {
        stopManagedCall('figure_changed')
        activeFigureIdRef.current = null
        setMessages([])
      }
      const [st, logs] = await Promise.all([
        apiDialogue.getState(currentBaseId),
        currentFigureId && activeFigureIdRef.current !== currentFigureId
          ? apiDialogue.getLogs(currentFigureId, 6).catch(() => [])
          : Promise.resolve(null),
      ])
      if (loadAttempt !== loadAttemptRef.current || activeBaseIdRef.current !== currentBaseId) return
      setDialogueState(st.state || 'idle')
      if (currentFigureId && logs) {
        activeFigureIdRef.current = currentFigureId
        const restored = [...logs]
          .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)))
          .flatMap(log => [
            {
              role: 'user' as const,
              text: String(log.user_input_text || ''),
              turnId: log.turn_id,
            },
            {
              role: 'assistant' as const,
              text: String(log.reply_text || ''),
              brainMode: log.brain_mode,
              turnId: log.turn_id,
            },
          ])
          .filter(message => message.text)
        setMessages(restored)
      }
    } catch {
      if (loadAttempt !== loadAttemptRef.current) return
      stopManagedCall('base_unavailable')
      activeBaseIdRef.current = null
      activeFigureIdRef.current = null
      setBaseId(null)
      setBaseData(null)
      setDialogueState('idle')
    }
  }, [navigate, requestedFigureId, stopManagedCall])

  useEffect(() => {
    loadData()
    const iv = setInterval(loadData, 2000)
    return () => clearInterval(iv)
  }, [loadData])

  useEffect(() => {
    if (!baseId) {
      setAsrAvailable(false)
      return
    }
    apiDialogue.getAsrStatus()
      .then(data => setAsrAvailable(data.available))
      .catch(() => setAsrAvailable(false))
  }, [baseId])

  useEffect(() => {
    const el = chatScrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  async function handleSend() {
    const currentBaseId = baseId
    if (!chatInput.trim() || !currentBaseId) return
    const text = chatInput.trim()
    setChatInput('')
    setMessages(m => [...m, { role: 'user', text }])
    setLoading(true)
    setError('')
    try {
      const res = await apiDialogue.sendText(currentBaseId, text)

      setMessages(m => [...m, {
        role: 'assistant',
        text: res.reply,
        brainMode: res.brain_mode,
      }])
      loadData()
    } catch (e: any) {
      setError(e.message || '发送失败')
    } finally {
      setLoading(false)
    }
  }

  async function startVoiceCall() {
    const currentBaseId = baseId
    if (!asrAvailable || !figure || !currentBaseId) return
    await startManagedCall(currentBaseId)
  }

  function endVoiceCall() {
    stopManagedCall('user_hangup')
  }

  const figure = baseData?.figure

  // 状态显示
  const voiceStateDisplay = {
    connecting: { icon: '', text: '正在连接' },
    listening: { icon: '', text: '正在听你说' },
    speaking: { icon: '', text: '正在回应' },
  }

  return (
    <div className="min-h-screen bg-castle relative overflow-hidden">
      <StarField count={18} />
      <div className="pointer-events-none absolute -top-28 left-1/2 h-72 w-72 -translate-x-1/2 rounded-full bg-white/62 blur-3xl" />

      <PageHeader
        title="继续交流"
        subtitle={figure?.name || '当前灵偶尚未就绪'}
        onBack={() => {
          if (isInCall) endVoiceCall()
          navigate('/home')
        }}
        extra={
          <span className={`rounded-full px-3 py-1 text-[11px] font-bold shadow-sm ring-1 ${
            dialogueState === 'idle' ? 'bg-white/75 text-purple-400 ring-white/80' :
            dialogueState === 'listening' ? 'bg-emerald-100 text-emerald-700 ring-emerald-200' :
            dialogueState === 'speaking' ? 'bg-yellow-100 text-yellow-700 ring-yellow-200' :
            'bg-purple-500 text-white ring-purple-300'
          }`}>
            {dialogueState === 'listening' ? '聆听中' : dialogueState === 'speaking' ? '回应中' : '待唤醒'}
          </span>
        }
      />

      <div className="relative z-10 mx-auto flex max-w-lg flex-col gap-4 px-4 pb-28">

        {/* 无灵偶空态引导 */}
        {!figure && (
          <div className="glass-card p-6 text-center">
            <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-3xl bg-purple-100 text-3xl">💬</div>
            <p className="mb-2 font-bold text-purple-900">还没有设置当前灵偶</p>
            <p className="mb-4 text-xs text-purple-400">返回主页继续完成当前灵偶设置</p>
            <button
              onClick={() => navigate('/home')}
              className="rounded-full bg-gradient-to-r from-purple-500 to-pink-500 px-4 py-2 text-sm font-bold text-white shadow-lg shadow-purple-300/40"
            >
              返回主页
            </button>
          </div>
        )}

        {/* Active figure */}
        <LiquidGlassPanel
          contentClassName="liquid-brand-surface p-4 text-white"
          radius={30}
          variant="hero"
        >
          <p className="mb-1 text-[10px] font-bold uppercase tracking-[0.25em] text-white/60">当前灵偶</p>
          {figure ? (
            <div className="soul-presence-card soul-presence-card--dialogue">
              <div className="soul-presence-card__stage">
                <div className="soul-presence-card__glow" />
                <SoulFigureStage figure={figure} className="soul-presence-card__figure" />
                <div className="soul-presence-card__shine" />
              </div>
              <div className="soul-presence-card__content">
                <p className="text-2xl font-black">{figure.name}</p>
                <p className="text-xs text-white/70">{figure.soul_profile?.archetype} · {figure.soul_profile?.address_user_as}</p>
                <button
                  onClick={() => navigate(`/soul/${figure.figure_id}`)}
                  className="mt-3 rounded-full bg-white px-4 py-2 text-xs font-black text-purple-950 shadow-lg shadow-black/15"
                >
                  档案与记忆
                </button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-white/70">无灵偶</p>
          )}
        </LiquidGlassPanel>

        {/* ============== 语音通话模式卡片（极简版）============== */}
        {figure && (
          <section className="glass-card p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="text-sm font-black text-purple-900">语音通话模式</p>
                <p className="text-[11px] font-medium text-purple-500">像打电话一样和当前灵偶聊天</p>
              </div>
              {isInCall && (
                <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${
                  voiceCallState === 'listening' ? 'bg-green-100 text-green-700' :
                  voiceCallState === 'speaking' ? 'bg-yellow-100 text-yellow-700' :
                  'bg-purple-100 text-purple-700'
                }`}>
                  {voiceStateDisplay[voiceCallState].icon} {voiceStateDisplay[voiceCallState].text}
                </span>
              )}
            </div>

            {/* 通话状态提示 */}
            {isInCall && (
              <div className="mb-3 rounded-2xl bg-white/30 p-3 text-center ring-1 ring-white/70 backdrop-blur-xl">
                <p aria-live="polite" className="font-bold text-purple-700">
                  {voiceHint || voiceStateDisplay[voiceCallState].text}
                </p>
              </div>
            )}
            {asrError && (
              <p role="alert" className="mb-3 rounded-2xl bg-red-50 px-3 py-2 text-xs font-semibold text-red-600 ring-1 ring-red-100">
                {asrError}
              </p>
            )}

            {/* 通话控制按钮 */}
            <div className="flex gap-3">
              {!isInCall ? (
                <button
                  onClick={startVoiceCall}
                  disabled={!asrAvailable}
                  className={`flex-1 rounded-2xl py-3 font-bold transition-all ${
                    asrAvailable
                      ? 'bg-gradient-to-r from-purple-500 to-pink-500 text-white shadow-lg shadow-purple-300/40'
                      : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                  }`}
                >
                  {voiceSnapshot.status === 'permission_denied'
                    ? '重新授权麦克风'
                    : '📞 开始语音通话'}
                </button>
              ) : (
                <button
                  onClick={endVoiceCall}
                  className="flex-1 rounded-2xl bg-gradient-to-r from-red-500 to-pink-500 py-3 font-bold text-white shadow-lg shadow-red-200/50"
                >
                  📴 挂断
                </button>
              )}
            </div>

            {/* 提示 */}
            {!isInCall && (
              <p className="mt-2 text-xs text-purple-400 text-center">
                {asrAvailable ? '点一下开始，像打电话一样对话' : '语音服务暂未配置'}
              </p>
            )}
            {isInCall && (
              <p className="mt-2 text-xs text-purple-400 text-center">
                建议戴耳机体验，灵偶回应时也可以直接打断
              </p>
            )}
          </section>
        )}

        {/* Chat messages */}
        <section className="glass-card flex max-h-80 min-h-56 flex-1 flex-col p-4">
          <p className="text-sm font-black text-purple-900 mb-2 shrink-0">对话记录</p>
          <div ref={chatScrollRef} className="flex-1 overflow-y-auto flex flex-col gap-3" style={{ WebkitOverflowScrolling: 'touch' }}>
            {messages.length === 0 && <p className="text-purple-300 text-sm text-center py-4">
              {isInCall ? '开始通话后可看到对话内容' : '唤醒后开始对话'}
            </p>}
            {messages.map((msg, i) => (
              <div key={msg.turnId ? `${msg.turnId}-${msg.role}` : i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start gap-2'}`}>
                {msg.role === 'assistant' && (
                  <span className="dialogue-reply-avatar">
                    {figure?.avatar_url ? <img src={figure.avatar_url} alt="" /> : <span>{figure?.name?.slice(0, 1) || '灵'}</span>}
                  </span>
                )}
                <div className={`flex max-w-[82%] flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                  <div className={`rounded-[20px] px-4 py-2.5 text-sm font-medium shadow-sm ${
                    msg.role === 'user'
                      ? 'bg-gradient-to-r from-purple-500 to-pink-500 text-white rounded-br-md'
                      : 'bg-white/85 text-purple-900 rounded-bl-md ring-1 ring-purple-100'
                  }`}>
                    {msg.text}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Chat input（仅非通话模式显示） */}
        {!isInCall && (
          <section className="glass-card p-4">
            <div className="flex gap-2">
              <input
                type="text"
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSend()}
                placeholder="输入对话内容..."
                className="flex-1 rounded-2xl border border-purple-100 bg-white/65 px-4 py-2.5 text-sm text-purple-900 placeholder-purple-300 focus:outline-none focus:ring-2 focus:ring-purple-300"
                disabled={loading || !figure}
              />
              <button
                onClick={handleSend}
                disabled={loading || !chatInput.trim() || !figure}
                className="btn-soul px-5 text-sm disabled:opacity-40"
              >
                {loading ? '...' : '发送'}
              </button>
            </div>
            {error && <p className="text-red-500 text-xs mt-2">{error}</p>}
          </section>
        )}

      </div>
    </div>
  )
}
