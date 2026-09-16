export type VoiceLifecycleStatus =
  | 'idle'
  | 'requesting_permission'
  | 'connecting'
  | 'listening'
  | 'speaking'
  | 'reconnecting'
  | 'permission_denied'
  | 'error'
  | 'replaced'

export type VoiceAudioStatus =
  | 'idle'
  | 'synthesized'
  | 'transferred'
  | 'decoded'
  | 'playing'
  | 'completed'
  | 'failed'

export interface VoiceCallSnapshot {
  status: VoiceLifecycleStatus
  active: boolean
  baseId: string | null
  sessionId: string | null
  hint: string
  error: string
  reconnectAttempt: number
  audioStatus: VoiceAudioStatus
  audioError: string
}

export interface VoiceServerMessage {
  type: string
  session_id?: string
  turn_id?: string
  turn_sequence?: number
  status?: string
  text?: string
  reply?: string
  brain_mode?: string
  message?: string
  stage?: string
  audio_id?: string
  content_type?: string
  byte_length?: number
  error_code?: string
  [key: string]: unknown
}

export interface VoiceCallControllerEvents {
  onState(snapshot: VoiceCallSnapshot): void
  onServerMessage(message: VoiceServerMessage): void
}

export interface VoiceCallDependencies {
  getUserMedia(constraints: MediaStreamConstraints): Promise<MediaStream>
  createAudioContext(): AudioContext
  createWebSocket(url: string, protocols: string[]): WebSocket
  createTicket(baseId: string): Promise<{ ticket: string }>
  websocketUrl(baseId: string): string
  setTimer(callback: () => void, delayMs: number): number
  clearTimer(timerId: number): void
  reconnectDelayMs?: number
  maxReconnectAttempts?: number
}

interface VoiceResources {
  attempt: number
  stream: MediaStream | null
  audioContext: AudioContext | null
  source: MediaStreamAudioSourceNode | null
  processor: ScriptProcessorNode | null
  mute: GainNode | null
  socket: WebSocket | null
  scheduledSources: Set<AudioBufferSourceNode>
  pendingAudio: VoiceAudioDescriptor[]
  playbackTimers: Set<number>
  pendingDecodes: number
  serverSpeaking: boolean
  audioGeneration: number
  nextStartTime: number
}

interface VoiceAudioDescriptor {
  audioId: string
  sessionId: string
  turnId: string
  contentType: string
}

const CONNECTING = 0
const OPEN = 1
const CLOSING = 2
const AUTH_CLOSE_CODES = new Set([4401, 4403, 4409])

export const INITIAL_VOICE_CALL_SNAPSHOT: VoiceCallSnapshot = {
  status: 'idle',
  active: false,
  baseId: null,
  sessionId: null,
  hint: '',
  error: '',
  reconnectAttempt: 0,
  audioStatus: 'idle',
  audioError: '',
}

function isPermissionDenied(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  return error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError'
}

function releaseStream(stream: MediaStream | null): void {
  stream?.getTracks().forEach(track => track.stop())
}

export class VoiceCallController {
  private snapshotValue: VoiceCallSnapshot = { ...INITIAL_VOICE_CALL_SNAPSHOT }
  private desiredActive = false
  private destroyed = false
  private attempt = 0
  private resources: VoiceResources | null = null
  private connectPromise: Promise<void> | null = null
  private reconnectTimer: number | null = null
  private reconnectAttempt = 0

  constructor(
    private readonly dependencies: VoiceCallDependencies,
    private readonly events: VoiceCallControllerEvents,
  ) {}

  get snapshot(): VoiceCallSnapshot {
    return { ...this.snapshotValue }
  }

  async start(baseId: string): Promise<void> {
    if (this.destroyed || !baseId) return
    const currentSocket = this.resources?.socket
    if (
      this.desiredActive
      && this.snapshotValue.baseId === baseId
      && (
        this.connectPromise
        || this.reconnectTimer !== null
        || (
          currentSocket
          && (
            currentSocket.readyState === CONNECTING
            || currentSocket.readyState === OPEN
          )
        )
      )
    ) {
      return this.connectPromise || Promise.resolve()
    }
    if (this.snapshotValue.baseId && this.snapshotValue.baseId !== baseId) {
      this.stop('base_changed')
    }
    this.desiredActive = true
    this.publish({
      baseId,
      error: '',
      sessionId: null,
    })
    this.clearReconnectTimer()

    return this.openAttempt(false)
  }

  stop(_reason = 'user_hangup'): void {
    if (this.destroyed && !this.desiredActive && !this.resources) return
    this.desiredActive = false
    this.attempt += 1
    this.connectPromise = null
    this.reconnectAttempt = 0
    this.clearReconnectTimer()
    this.releaseResources(this.resources, true)
    this.resources = null
    this.publish({
      status: 'idle',
      active: false,
      sessionId: null,
      hint: '',
      error: '',
      reconnectAttempt: 0,
      audioStatus: 'idle',
      audioError: '',
    })
  }

  destroy(): void {
    if (this.destroyed) return
    this.destroyed = true
    this.stop('destroyed')
  }

  private openAttempt(isReconnect: boolean): Promise<void> {
    const attempt = ++this.attempt
    const task = this.setupAttempt(attempt, isReconnect)
      .finally(() => {
        if (this.connectPromise === task) this.connectPromise = null
      })
    this.connectPromise = task
    return task
  }

  private async setupAttempt(attempt: number, isReconnect: boolean): Promise<void> {
    const resources: VoiceResources = {
      attempt,
      stream: null,
      audioContext: null,
      source: null,
      processor: null,
      mute: null,
      socket: null,
      scheduledSources: new Set(),
      pendingAudio: [],
      playbackTimers: new Set(),
      pendingDecodes: 0,
      serverSpeaking: false,
      audioGeneration: 0,
      nextStartTime: 0,
    }
    this.resources = resources
    this.publish({
      status: isReconnect ? 'reconnecting' : 'requesting_permission',
      active: true,
      hint: isReconnect ? '连接中断，正在重连…' : '正在请求麦克风权限…',
      error: '',
      reconnectAttempt: this.reconnectAttempt,
    })

    try {
      const stream = await this.dependencies.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false,
          sampleRate: 48000,
        },
      })
      resources.stream = stream
      if (!this.isCurrent(attempt)) {
        this.releaseResources(resources, true)
        return
      }

      const audioContext = this.dependencies.createAudioContext()
      resources.audioContext = audioContext
      if (audioContext.state === 'suspended') {
        await audioContext.resume()
      }
      if (!this.isCurrent(attempt)) {
        this.releaseResources(resources, true)
        return
      }
      resources.source = audioContext.createMediaStreamSource(stream)
      resources.processor = audioContext.createScriptProcessor(4096, 1, 1)
      resources.mute = audioContext.createGain()
      resources.mute.gain.value = 0
      resources.source.connect(resources.processor)
      resources.processor.connect(resources.mute)
      resources.mute.connect(audioContext.destination)
      resources.processor.onaudioprocess = event => {
        this.forwardAudio(resources, event)
      }

      this.publish({
        status: 'connecting',
        active: true,
        hint: '正在连接语音服务…',
      })
      const baseId = this.snapshotValue.baseId
      if (!baseId) throw new Error('底座不可用')
      const { ticket } = await this.dependencies.createTicket(baseId)
      if (!this.isCurrent(attempt)) {
        this.releaseResources(resources, true)
        return
      }

      const socket = this.dependencies.createWebSocket(
        this.dependencies.websocketUrl(baseId),
        ['lingou.asr.v1', `lingou.ticket.${ticket}`],
      )
      resources.socket = socket
      socket.binaryType = 'arraybuffer'
      socket.onopen = () => this.handleOpen(resources)
      socket.onmessage = event => this.handleMessage(resources, event)
      socket.onerror = () => this.handleSocketError(resources)
      socket.onclose = event => this.handleClose(resources, event)
    } catch (error) {
      this.releaseResources(resources, true)
      if (!this.isCurrent(attempt)) return
      this.resources = null
      this.desiredActive = false
      this.attempt += 1
      if (isPermissionDenied(error)) {
        this.publish({
          status: 'permission_denied',
          active: false,
          hint: '',
          error: '麦克风权限被拒绝，请允许访问后重试',
        })
      } else {
        this.publish({
          status: 'error',
          active: false,
          hint: '',
          error: error instanceof Error ? error.message : '语音通话启动失败',
        })
      }
    }
  }

  private handleOpen(resources: VoiceResources): void {
    if (!this.isCurrent(resources.attempt) || this.resources !== resources) {
      this.releaseResources(resources, true)
      return
    }
    this.reconnectAttempt = 0
    this.publish({
      status: 'listening',
      active: true,
      hint: '聆听中…',
      error: '',
      reconnectAttempt: 0,
      audioStatus: 'idle',
      audioError: '',
    })
  }

  private handleMessage(resources: VoiceResources, event: MessageEvent): void {
    if (!this.isCurrent(resources.attempt) || this.resources !== resources) return
    if (event.data instanceof ArrayBuffer) {
      const descriptor = resources.pendingAudio.shift()
      if (!descriptor) {
        this.publish({
          audioStatus: 'failed',
          audioError: '收到缺少说明信息的音频，已停止播放',
          error: '语音回复协议异常，请重试',
        })
        return
      }
      void this.scheduleAudio(resources, descriptor, event.data)
      return
    }
    let message: VoiceServerMessage
    try {
      message = JSON.parse(String(event.data)) as VoiceServerMessage
    } catch {
      this.publish({ error: '语音服务返回了无法识别的消息' })
      return
    }
    if (message.session_id) {
      this.publish({ sessionId: message.session_id })
    }
    switch (message.type) {
      case 'interim':
        this.publish({ hint: `识别中：${message.text || ''}` })
        break
      case 'final':
        this.publish({ hint: '灵偶回复中…' })
        break
      case 'speaking':
        if (message.status === 'start') {
          resources.serverSpeaking = true
          this.publish({
            status: 'speaking',
            active: true,
            hint: '正在生成语音…',
            audioStatus: 'idle',
            audioError: '',
          })
        } else {
          resources.serverSpeaking = false
          this.finishSpeakingIfIdle(resources)
        }
        break
      case 'audio_output':
        this.handleAudioOutput(resources, message)
        break
      case 'barge_in':
        resources.serverSpeaking = false
        this.publish({
          status: 'listening',
          active: true,
          hint: '已打断，重新聆听…',
          audioStatus: 'idle',
          audioError: '',
        })
        break
      case 'stop_audio':
        resources.serverSpeaking = false
        this.stopScheduledAudio(resources)
        this.publish({
          status: 'listening',
          active: true,
          hint: '聆听中…',
          audioStatus: 'idle',
          audioError: '',
        })
        break
      case 'session_replaced':
        this.events.onServerMessage(message)
        this.terminate('replaced', '此底座已在另一个窗口开始语音通话')
        return
      case 'error':
        this.publish({ error: message.message || '语音服务错误' })
        break
    }
    this.events.onServerMessage(message)
  }

  private handleAudioOutput(
    resources: VoiceResources,
    message: VoiceServerMessage,
  ): void {
    switch (message.stage) {
      case 'synthesized': {
        if (!message.audio_id || !message.session_id || !message.turn_id) {
          this.publish({
            audioStatus: 'failed',
            audioError: '语音元数据不完整',
            error: '语音回复协议异常，请重试',
          })
          return
        }
        resources.pendingAudio.push({
          audioId: message.audio_id,
          sessionId: message.session_id,
          turnId: message.turn_id,
          contentType: message.content_type || 'audio/mpeg',
        })
        this.publish({
          status: 'speaking',
          active: true,
          hint: '语音已合成，正在传输…',
          audioStatus: 'synthesized',
          audioError: '',
        })
        break
      }
      case 'transferred':
        this.publish({
          status: 'speaking',
          active: true,
          hint: '语音已传输，正在解码…',
          audioStatus: 'transferred',
        })
        break
      case 'failed': {
        const messageText = message.message || '语音播放失败，请重试'
        resources.serverSpeaking = false
        this.stopScheduledAudio(resources)
        this.publish({
          audioStatus: 'failed',
          audioError: messageText,
          error: messageText,
          hint: '',
        })
        this.finishSpeakingIfIdle(resources)
        break
      }
    }
  }

  private handleSocketError(resources: VoiceResources): void {
    if (!this.isCurrent(resources.attempt) || this.resources !== resources) return
    this.publish({ error: '语音连接发生异常' })
  }

  private handleClose(resources: VoiceResources, event: CloseEvent): void {
    if (this.resources !== resources) return
    this.releaseResources(resources, false)
    this.resources = null
    this.connectPromise = null
    this.attempt += 1

    if (event.code === 4410) {
      this.terminate('replaced', '此底座已在另一个窗口开始语音通话')
      return
    }
    if (AUTH_CLOSE_CODES.has(event.code)) {
      this.terminate('error', '语音连接身份无效，请重新登录后再试')
      return
    }
    if (!this.desiredActive || this.destroyed) {
      this.publish({ status: 'idle', active: false, hint: '' })
      return
    }
    this.scheduleReconnect()
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null || !this.desiredActive || this.destroyed) return
    const maximum = this.dependencies.maxReconnectAttempts ?? 3
    if (this.reconnectAttempt >= maximum) {
      this.terminate('error', '语音连接多次中断，请手动重试')
      return
    }
    this.reconnectAttempt += 1
    this.publish({
      status: 'reconnecting',
      active: true,
      hint: `连接中断，正在重连（${this.reconnectAttempt}/${maximum}）…`,
      error: '',
      reconnectAttempt: this.reconnectAttempt,
    })
    this.reconnectTimer = this.dependencies.setTimer(() => {
      this.reconnectTimer = null
      if (!this.desiredActive || this.destroyed || this.connectPromise) return
      void this.openAttempt(true)
    }, this.dependencies.reconnectDelayMs ?? 1500)
  }

  private terminate(status: 'error' | 'replaced', error: string): void {
    this.desiredActive = false
    this.attempt += 1
    this.connectPromise = null
    this.clearReconnectTimer()
    this.releaseResources(this.resources, true)
    this.resources = null
    this.publish({
      status,
      active: false,
      sessionId: null,
      hint: '',
      error,
    })
  }

  private forwardAudio(resources: VoiceResources, event: AudioProcessingEvent): void {
    event.outputBuffer.getChannelData(0).fill(0)
    const socket = resources.socket
    const context = resources.audioContext
    if (
      !this.isCurrent(resources.attempt)
      || !socket
      || socket.readyState !== OPEN
      || !context
    ) return

    const input = event.inputBuffer.getChannelData(0)
    const ratio = context.sampleRate / 16000
    const outputLength = Math.floor(input.length / ratio)
    const pcm = new Int16Array(outputLength)
    for (let index = 0; index < outputLength; index += 1) {
      const sourceIndex = index * ratio
      const floorIndex = Math.floor(sourceIndex)
      const fraction = sourceIndex - floorIndex
      const next = floorIndex + 1 < input.length ? input[floorIndex + 1] : input[floorIndex]
      const sample = input[floorIndex] * (1 - fraction) + next * fraction
      const clamped = Math.max(-1, Math.min(1, sample || 0))
      pcm[index] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff
    }
    socket.send(new Uint8Array(pcm.buffer))
  }

  private async scheduleAudio(
    resources: VoiceResources,
    descriptor: VoiceAudioDescriptor,
    payload: ArrayBuffer,
  ): Promise<void> {
    const context = resources.audioContext
    if (!context) return
    const audioGeneration = resources.audioGeneration
    resources.pendingDecodes += 1
    let decodePending = true
    try {
      const decoded = await context.decodeAudioData(payload.slice(0))
      if (audioGeneration === resources.audioGeneration) {
        resources.pendingDecodes = Math.max(0, resources.pendingDecodes - 1)
      }
      decodePending = false
      if (
        !this.isCurrent(resources.attempt)
        || this.resources !== resources
        || resources.audioContext !== context
        || audioGeneration !== resources.audioGeneration
      ) return
      this.sendPlaybackReceipt(resources, descriptor, 'decoded')
      this.publish({
        status: 'speaking',
        active: true,
        hint: '语音已解码，准备播放…',
        audioStatus: 'decoded',
      })
      const source = context.createBufferSource()
      source.buffer = decoded
      source.connect(context.destination)
      resources.scheduledSources.add(source)
      let playbackStarted = false
      let startTimer: number | null = null
      const reportStarted = () => {
        if (playbackStarted) return
        playbackStarted = true
        if (startTimer !== null) {
          resources.playbackTimers.delete(startTimer)
          startTimer = null
        }
        if (!this.isCurrent(resources.attempt) || !resources.scheduledSources.has(source)) {
          return
        }
        this.sendPlaybackReceipt(resources, descriptor, 'playback_started')
        this.publish({
          status: 'speaking',
          active: true,
          hint: '灵偶说话中…',
          audioStatus: 'playing',
        })
      }
      source.onended = () => {
        reportStarted()
        resources.scheduledSources.delete(source)
        source.disconnect()
        this.sendPlaybackReceipt(resources, descriptor, 'playback_completed')
        this.publish({
          audioStatus: 'completed',
          audioError: '',
        })
        this.finishSpeakingIfIdle(resources)
      }
      const startTime = Math.max(context.currentTime, resources.nextStartTime)
      resources.nextStartTime = startTime + decoded.duration
      source.start(startTime)
      const delayMs = Math.max(0, (startTime - context.currentTime) * 1000)
      if (delayMs <= 1) {
        reportStarted()
      } else {
        startTimer = this.dependencies.setTimer(reportStarted, delayMs)
        resources.playbackTimers.add(startTimer)
      }
    } catch (error) {
      if (decodePending && audioGeneration === resources.audioGeneration) {
        resources.pendingDecodes = Math.max(0, resources.pendingDecodes - 1)
      }
      if (audioGeneration !== resources.audioGeneration) return
      this.sendPlaybackReceipt(
        resources,
        descriptor,
        'playback_failed',
        error instanceof Error ? error.message : 'decode_failed',
      )
      this.publish({
        audioStatus: 'failed',
        audioError: '收到语音回复，但音频解码失败',
        error: '收到语音回复，但音频解码失败',
      })
      this.finishSpeakingIfIdle(resources)
    }
  }

  private sendPlaybackReceipt(
    resources: VoiceResources,
    descriptor: VoiceAudioDescriptor,
    stage: 'decoded' | 'playback_started' | 'playback_completed' | 'playback_failed',
    error?: string,
  ): void {
    const socket = resources.socket
    if (
      !this.isCurrent(resources.attempt)
      || !socket
      || socket.readyState !== OPEN
    ) return
    socket.send(JSON.stringify({
      type: 'audio_playback',
      stage,
      session_id: descriptor.sessionId,
      turn_id: descriptor.turnId,
      audio_id: descriptor.audioId,
      client_time_ms: Date.now(),
      ...(error ? { error } : {}),
    }))
  }

  private finishSpeakingIfIdle(resources: VoiceResources): void {
    if (
      resources.serverSpeaking
      || resources.pendingAudio.length > 0
      || resources.pendingDecodes > 0
      || resources.scheduledSources.size > 0
    ) return
    this.publish({
      status: 'listening',
      active: true,
      hint: '聆听中…',
    })
  }

  private stopScheduledAudio(resources: VoiceResources): void {
    resources.audioGeneration += 1
    resources.playbackTimers.forEach(timerId => {
      this.dependencies.clearTimer(timerId)
    })
    resources.playbackTimers.clear()
    resources.scheduledSources.forEach(source => {
      source.onended = null
      try {
        source.stop()
      } catch {
        // Source may already have ended.
      }
      source.disconnect()
    })
    resources.scheduledSources.clear()
    resources.pendingAudio = []
    resources.pendingDecodes = 0
    resources.nextStartTime = 0
  }

  private releaseResources(resources: VoiceResources | null, closeSocket: boolean): void {
    if (!resources) return
    this.stopScheduledAudio(resources)
    const socket = resources.socket
    resources.socket = null
    if (socket) {
      socket.onopen = null
      socket.onmessage = null
      socket.onerror = null
      socket.onclose = null
      if (closeSocket && socket.readyState < CLOSING) socket.close()
    }
    if (resources.processor) {
      resources.processor.onaudioprocess = null
      resources.processor.disconnect()
      resources.processor = null
    }
    resources.source?.disconnect()
    resources.source = null
    resources.mute?.disconnect()
    resources.mute = null
    releaseStream(resources.stream)
    resources.stream = null
    const context = resources.audioContext
    resources.audioContext = null
    if (context && context.state !== 'closed') {
      void context.close()
    }
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer === null) return
    this.dependencies.clearTimer(this.reconnectTimer)
    this.reconnectTimer = null
  }

  private isCurrent(attempt: number): boolean {
    return (
      !this.destroyed
      && this.desiredActive
      && attempt === this.attempt
    )
  }

  private publish(patch: Partial<VoiceCallSnapshot>): void {
    this.snapshotValue = { ...this.snapshotValue, ...patch }
    this.events.onState({ ...this.snapshotValue })
  }
}
