import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiBases, apiFigures, apiBrain } from '../services/api'
import StarField from '../components/StarField'
import PageHeader from '../components/PageHeader'
import LiquidGlassPanel from '../components/LiquidGlassPanel'
import SoulFigureStage from '../components/SoulFigureStage'

const BRAIN_MODES = [
  { key: 'auto', label: '自动' },
  { key: 'online', label: '强制在线' },
  { key: 'offline', label: '强制离线' },
]

const MOOD_LABELS: Record<string, string> = {
  happy: '开心',
  lonely: '孤独',
  attached: '依恋',
  annoyed: '烦躁',
  attention: '关注',
  sleepy: '困倦',
}

function getMoodHighlights(emotion: Record<string, number>) {
  return Object.entries(emotion || {})
    .filter(([key, value]) => key !== 'last_dialogue_at' && typeof value === 'number')
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([key]) => MOOD_LABELS[key] || key)
}

// 语音通话状态机（由后端驱动）
type VoiceCallState = 'idle' | 'listening' | 'speaking'

interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  brainMode?: string
  streaming?: boolean
}

export default function DialogueDebugPage() {
  const navigate = useNavigate()
  const [baseId] = useState('BASE-001')
  const [baseData, setBaseData] = useState<any>(null)
  const [figures, setFigures] = useState<any[]>([])
  const [dialogueState, setDialogueState] = useState('idle')
  const [brainMode, setBrainMode] = useState('auto')
  const [brainStatus, setBrainStatus] = useState<any>(null)
  const [showBrainSettings, setShowBrainSettings] = useState(false)

  const [chatInput, setChatInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const chatScrollRef = useRef<HTMLDivElement>(null)

  // ============== 语音通话模式状态（由后端事件驱动）==============
  const [isInCall, setIsInCall] = useState(false)
  const [voiceCallState, setVoiceCallState] = useState<VoiceCallState>('idle')
  const [voiceHint, setVoiceHint] = useState('')
  const [asrError, setAsrError] = useState('')
  const [asrAvailable, setAsrAvailable] = useState(false)

  // 通话资源 refs
  const audioContextRef = useRef<AudioContext | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const connectingRef = useRef(false)  // 防止并发 WS 连接
  const manualCloseRef = useRef(false) // 标记主动关闭，避免错误重连
  const reconnectTimerRef = useRef<number | null>(null)  // 重连 debounce
  const isSpeakingRef = useRef(false)
  const scheduledSourcesRef = useRef<AudioBufferSourceNode[]>([])  // 已排程的音频源列表
  const nextStartTimeRef = useRef(0)  // 下一段音频的播放开始时间

  const loadData = useCallback(async () => {
    try {
      const [bd, figs] = await Promise.all([
        apiBases.get(baseId).catch(() => null),
        apiFigures.list().catch(() => []),
      ])
      setBaseData(bd)
      setFigures(figs)

      const st = await fetch(`/api/dialogue/state?base_id=${baseId}`).then(r => r.json()).catch(() => ({}))
      setDialogueState(st.state || 'idle')

      const bs = await apiBrain.status(baseId).catch(() => ({}))
      setBrainStatus(bs)
    } catch {}
  }, [baseId])

  useEffect(() => {
    loadData()
    const iv = setInterval(loadData, 2000)
    return () => clearInterval(iv)
  }, [loadData])

  useEffect(() => {
    fetch('/api/asr/status')
      .then(r => r.json())
      .then(data => setAsrAvailable(data.available))
      .catch(() => setAsrAvailable(false))
  }, [])

  useEffect(() => {
    const el = chatScrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  async function handleSend() {
    if (!chatInput.trim()) return
    const text = chatInput.trim()
    setChatInput('')
    setMessages(m => [...m, { role: 'user', text }])
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/dialogue/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ base_id: baseId, text }),
      }).then(r => r.json())

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

  async function handleBrainMode(mode: string) {
    try {
      await apiBrain.setMode(mode, baseId)
      setBrainMode(mode)
    } catch {}
  }

  // ============== 清理通话资源 ==============
  function cleanupCall() {
    // 关闭 WebSocket
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    // 停止音频处理
    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current = null
    }
    if (sourceRef.current) {
      sourceRef.current.disconnect()
      sourceRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop())
      streamRef.current = null
    }

    // 关闭 AudioContext
    if (audioContextRef.current) {
      audioContextRef.current.close()
      audioContextRef.current = null
    }
  }

  async function handleAudioMessage(audioBuffer: ArrayBuffer) {
    try {
      const audioContext = audioContextRef.current
      if (!audioContext) {
        console.warn('[VoiceCall] AudioContext 未初始化，跳过音频播放')
        return
      }

      // 解码 mp3 数据
      const audioBufferDecoded = await audioContext.decodeAudioData(audioBuffer)
      
      // 创建音频源节点
      const source = audioContext.createBufferSource()
      source.buffer = audioBufferDecoded
      
      // 维护音频源列表（用于打断时停止）
      scheduledSourcesRef.current.push(source)
      
      // 计算播放开始时间（排队播放）
      const currentTime = audioContext.currentTime
      const startTime = Math.max(currentTime, nextStartTimeRef.current)
      
      // 更新下一段的开始时间
      nextStartTimeRef.current = startTime + audioBufferDecoded.duration

      // 连接到输出（使用同一个 AudioContext，让浏览器 AEC 能消回声）
      source.connect(audioContext.destination)
      
      // 开始播放
      source.start(startTime)
      
      console.log(`[VoiceCall] 音频播放调度：时长=${audioBufferDecoded.duration.toFixed(2)}s，开始时间=${startTime.toFixed(2)}s`)
    } catch (e) {
      console.error('[VoiceCall] 音频播放失败:', e)
    }
  }

  // 【Barge-in】停止所有已排程的音频
  function stopAllAudio() {
    const sources = scheduledSourcesRef.current
    if (sources.length > 0) {
      console.log(`[VoiceCall] 停止 ${sources.length} 个已排程的音频源`)
      sources.forEach(source => {
        try {
          source.stop()
        } catch (e) {
          // 忽略已停止的
        }
      })
      scheduledSourcesRef.current = []
      nextStartTimeRef.current = 0
    }
  }

  // ============== 开始语音通话（极简版：只上传音频，状态由后端驱动）==============
  async function startVoiceCall() {
    if (!asrAvailable || !figure) {
      setAsrError('语音服务未配置或无灵偶')
      return
    }

    // 互斥锁：已有连接中或正在连接，直接返回
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      console.log('[VoiceCall] WS 已在连接中，忽略重复调用')
      return
    }
    if (connectingRef.current) {
      console.log('[VoiceCall] 正在连接中，忽略重复调用')
      return
    }

    connectingRef.current = true
    manualCloseRef.current = false  // 清除主动关闭标志
    setAsrError('')
    setIsInCall(true)
    setMessages([])
    setVoiceCallState('listening')
    setVoiceHint('🎧 聆听中...')

    try {
      // 获取麦克风权限（开启回声消除）
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false,   // 关键：开着会放大说完后的底噪，火山永远判不出"说完"
          sampleRate: 48000,  // 请求48kHz，让AudioContext用原生采样率
        },
      })
      streamRef.current = stream

      // 创建 AudioContext（用原生采样率，避免重采样杂音）
      const audioContext = new AudioContext()
      audioContextRef.current = audioContext
      const nativeSampleRate = audioContext.sampleRate
      console.log(`[VoiceCall] AudioContext 采样率: ${nativeSampleRate}Hz`)

      // 创建音频处理节点
      const source = audioContext.createMediaStreamSource(stream)
      sourceRef.current = source
      const processor = audioContext.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor

      // 【关键修复】零增益节点中转：保证 onaudioprocess 触发但完全不出声
      const mute = audioContext.createGain()
      mute.gain.value = 0  // 完全静音
      source.connect(processor)
      processor.connect(mute)
      mute.connect(audioContext.destination)

      // 连接 WebSocket（带上 base_id）
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${wsProtocol}//${window.location.host}/api/asr/stream?base_id=${baseId}`
      const ws = new WebSocket(wsUrl)
      ws.binaryType = 'arraybuffer'  // 设置二进制类型
      wsRef.current = ws

      ws.onopen = () => {
        console.log('[VoiceCall] WebSocket 已连接')
        setVoiceCallState('listening')
        setVoiceHint('🎧 聆听中...')
      }

      // ============== 监听后端消息（后端事件驱动）==============
      ws.onmessage = (event) => {
        try {
          // 二进制消息：灵偶音频（mp3）
          if (event.data instanceof ArrayBuffer) {
            handleAudioMessage(event.data)
            return
          }
          
          // 文本消息：JSON 格式
          const data = JSON.parse(event.data)
          console.log('[VoiceCall] WS 消息:', data)

          switch (data.type) {
            case 'interim':
              // 中间结果：显示识别中的文本
              setVoiceHint('🎤 识别中: ' + data.text)
              break

            case 'final':
              // 火山判定说完，用户文本已收到
              setVoiceHint('💬 灵偶回复中...')
              // 添加用户消息到聊天记录
              setMessages(m => [...m, { role: 'user', text: data.text }])
              break

            case 'reply_chunk':
              // 逐句流式：追加到当前这条灵偶消息
              setMessages(m => {
                const last = m[m.length - 1]
                if (last && last.role === 'assistant' && last.streaming) {
                  const updated = [...m]
                  updated[updated.length - 1] = { ...last, text: last.text + data.text }
                  return updated
                }
                return [...m, { role: 'assistant', text: data.text, streaming: true, brainMode: undefined }]
              })
              break

            case 'reply':
              // 整段到达：标记当前流式消息收尾（补 brainMode，去掉 streaming 标记）
              setMessages(m => {
                const last = m[m.length - 1]
                if (last && last.role === 'assistant' && last.streaming) {
                  const updated = [...m]
                  updated[updated.length - 1] = { ...last, streaming: false, brainMode: data.brain_mode }
                  return updated
                }
                // 没有流式消息时（兜底）仍然新增一条
                return [...m, { role: 'assistant', text: data.reply, brainMode: data.brain_mode }]
              })
              break

            case 'speaking':
              // 灵偶说话状态（不再控制麦克风开关，靠 AEC 消回声）
              if (data.status === 'start') {
                setVoiceCallState('speaking')
                setVoiceHint('💬 灵偶说话中...')
                isSpeakingRef.current = true
              } else {
                setVoiceCallState('listening')
                setVoiceHint('🎧 聆听中...')
                isSpeakingRef.current = false
              }
              break

            case 'barge_in':
              // 打断：显示用户新话和打断提示
              setMessages(m => [
                ...m,
                { role: 'user', text: data.text },
              ])
              setVoiceHint('🔄 被打断，重新聆听...')
              break

            case 'stop_audio':
              // 【Barge-in】停止所有已排程的音频，立即回到聆听态
              console.log('[VoiceCall] 收到 stop_audio，停止所有音频')
              stopAllAudio()
              setVoiceCallState('listening')
              setVoiceHint('🎧 聆听中...')
              isSpeakingRef.current = false
              break

            case 'error':
              setAsrError(data.message || '未知错误')
              break
          }
        } catch (e) {
          console.error('[VoiceCall] 解析消息失败:', e)
        }
      }

      ws.onerror = () => {
        setAsrError('WebSocket 连接失败')
      }

      ws.onclose = () => {
        wsRef.current = null
        connectingRef.current = false  // 连接结束

        // 主动关闭，不重连
        if (manualCloseRef.current) {
          console.log('[VoiceCall] 主动关闭，不重连')
          return
        }

        // 非主动关闭，debounce 1.5s 后重连（确保旧资源已释放）
        if (reconnectTimerRef.current) {
          clearTimeout(reconnectTimerRef.current)
        }
        reconnectTimerRef.current = window.setTimeout(() => {
          reconnectTimerRef.current = null
          if (isInCall) {
            console.log('[VoiceCall] 尝试重新连接...')
            startVoiceCall()
          }
        }, 1500)
      }

      // 实时发送 PCM 数据（降采样到 16kHz）
      // 双保险：零增益节点 + 输出填零
      processor.onaudioprocess = (event) => {
        // 静音输出：把输出缓冲区填零
        const out = event.outputBuffer.getChannelData(0)
        out.fill(0)

        if (!ws || ws.readyState !== WebSocket.OPEN) return

        const inputData = event.inputBuffer.getChannelData(0)
        
        // 【关键】降采样：从原生采样率降到 16kHz（线性插值）
        const targetSampleRate = 16000
        const ratio = nativeSampleRate / targetSampleRate
        const outputLength = Math.floor(inputData.length / ratio)
        const downsampled = new Float32Array(outputLength)
        
        for (let i = 0; i < outputLength; i++) {
          const srcIndex = i * ratio
          const floorIndex = Math.floor(srcIndex)
          const frac = srcIndex - floorIndex
          
          if (floorIndex + 1 < inputData.length) {
            // 线性插值
            downsampled[i] = inputData[floorIndex] * (1 - frac) + inputData[floorIndex + 1] * frac
          } else {
            downsampled[i] = inputData[floorIndex] || 0
          }
        }
        
        // Float32 → Int16 PCM
        const pcm16 = new Int16Array(downsampled.length)
        for (let i = 0; i < downsampled.length; i++) {
          const s = Math.max(-1, Math.min(1, downsampled[i]))
          pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
        }
        ws.send(new Uint8Array(pcm16.buffer))
      }

      // 连接成功
      connectingRef.current = false

    } catch (e: any) {
      connectingRef.current = false  // 连接失败也要重置
      setAsrError(e.message || '无法获取麦克风权限')
      cleanupCall()
      setIsInCall(false)
      setVoiceCallState('idle')
    }
  }

  // ============== 结束语音通话 ==============
  function endVoiceCall() {
    manualCloseRef.current = true  // 标记主动关闭，避免触发重连
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    cleanupCall()
    setIsInCall(false)
    setVoiceCallState('idle')
    setVoiceHint('')
  }

  const figure = baseData?.figure
  const emotion = figure?.soul_profile?.emotion_state || {}
  const moodHighlights = getMoodHighlights(emotion)

  // 状态显示
  const voiceStateDisplay = {
    idle: { icon: '', text: '待唤醒' },
    listening: { icon: '', text: '正在听你说' },
    speaking: { icon: '', text: '正在回应' },
  }

  return (
    <div className="min-h-screen bg-castle relative overflow-hidden">
      <StarField count={18} />
      <div className="pointer-events-none absolute -top-28 left-1/2 h-72 w-72 -translate-x-1/2 rounded-full bg-white/62 blur-3xl" />

      <PageHeader
        title="灵魂对话"
        subtitle={`底座 ${baseId} · ${figure?.name || '无灵偶'}`}
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
            <p className="mb-4 text-xs text-purple-400">请先在「我的灵偶」选择一个灵偶</p>
            <button
              onClick={() => navigate('/home')}
              className="rounded-full bg-gradient-to-r from-purple-500 to-pink-500 px-4 py-2 text-sm font-bold text-white shadow-lg shadow-purple-300/40"
            >
              去我的灵偶选择
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
                <div className="mt-3 flex flex-wrap gap-2">
                  {moodHighlights.map(label => (
                    <span key={label} className="rounded-full bg-white/18 px-2.5 py-1 text-xs font-semibold text-white ring-1 ring-white/20">
                      {label}
                    </span>
                  ))}
                </div>
                <button
                  onClick={() => navigate(`/soul/${figure.figure_id}`)}
                  className="mt-3 rounded-full bg-white px-4 py-2 text-xs font-black text-purple-950 shadow-lg shadow-black/15"
                >
                  羁绊主页
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
                <p className="font-bold text-purple-700">
                  {voiceHint || voiceStateDisplay[voiceCallState].text}
                </p>
              </div>
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
                  📞 开始语音通话
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
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start gap-2'}`}>
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
                  {msg.brainMode && showBrainSettings && (
                    <span className="mt-1 rounded-full bg-white/60 px-2 py-0.5 text-xs text-purple-400 ring-1 ring-white/70">
                      {msg.brainMode === 'online' ? '在线回应' : '本地回应'}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Chat input（仅非通话模式显示） */}
        {!isInCall && (
          <section className="glass-card p-4">
            {asrError && (
              <p className="mb-2 text-red-500 text-xs">{asrError}</p>
            )}
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

        {/* Brain mode selector */}
        <section className="glass-card p-4">
          <button
            onClick={() => setShowBrainSettings(!showBrainSettings)}
            className="flex w-full items-center justify-between text-left"
          >
            <div>
              <p className="text-sm font-black text-purple-900">调试设置</p>
              <p className="text-[11px] font-medium text-purple-400">高级模式、连接状态与回退信息</p>
            </div>
            <span className="rounded-full bg-white/65 px-2.5 py-1 text-[10px] font-bold text-purple-500 ring-1 ring-white/70">
              {showBrainSettings ? '收起' : '高级'}
            </span>
          </button>

          {showBrainSettings && (
            <div className="mt-4">
              <div className="flex gap-2">
                {BRAIN_MODES.map(m => (
                  <button
                    key={m.key}
                    onClick={() => handleBrainMode(m.key)}
                    className={`flex-1 rounded-2xl py-2 text-sm font-bold transition-all ${
                      brainMode === m.key
                        ? 'bg-gradient-to-r from-purple-500 to-pink-500 text-white shadow-lg shadow-purple-300/35'
                        : 'bg-white/65 text-purple-600 ring-1 ring-purple-100 hover:bg-purple-50'
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
              {brainStatus && (
                <p className="mt-3 rounded-2xl bg-white/55 px-3 py-2 text-xs text-purple-400 ring-1 ring-white/70">
                  API Key: {brainStatus.has_api_key ? '已配置' : '未配置'}
                  {brainStatus.fallback_reason && <span className="text-orange-500"> · 回退原因: {brainStatus.fallback_reason}</span>}
                </p>
              )}
            </div>
          )}
        </section>

        {/* Figure list */}
        {figures.length > 0 && (
          <section className="glass-card p-4">
            <p className="mb-3 text-sm font-black text-purple-900">灵偶列表</p>
            <div className="flex flex-wrap gap-2">
              {figures.map(fig => (
                <button
                  key={fig.figure_id}
                  onClick={async () => {
                    try {
                      await apiBases.setActiveFigure(baseId, fig.figure_id)
                      loadData()
                    } catch {}
                  }}
                  className={`soul-switch-chip ${
                    figure?.figure_id === fig.figure_id
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
