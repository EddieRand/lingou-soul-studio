import type { VoicePreviewAudio, VoicePreviewRequest } from './api'

export type VoicePreviewStatus =
  | 'idle'
  | 'synthesizing'
  | 'transferred'
  | 'decoded'
  | 'playing'
  | 'completed'
  | 'error'

export interface VoicePreviewSnapshot {
  status: VoicePreviewStatus
  targetKey: string | null
  speaker: string
  engine: string
  source: string
  error: string
  timestamps: Partial<Record<
    'requested' | 'synthesized' | 'transferred' | 'decoded' | 'playbackStarted' | 'playbackCompleted',
    number
  >>
}

export interface VoicePreviewDependencies {
  fetchAudio(request: VoicePreviewRequest, signal: AbortSignal): Promise<VoicePreviewAudio>
  createAudio(): HTMLAudioElement
  createObjectURL(blob: Blob): string
  revokeObjectURL(url: string): void
  now(): number
}

export interface VoicePreviewEvents {
  onState(snapshot: VoicePreviewSnapshot): void
}

export const INITIAL_VOICE_PREVIEW_SNAPSHOT: VoicePreviewSnapshot = {
  status: 'idle',
  targetKey: null,
  speaker: '',
  engine: '',
  source: '',
  error: '',
  timestamps: {},
}

export class VoicePreviewController {
  private snapshotValue: VoicePreviewSnapshot = {
    ...INITIAL_VOICE_PREVIEW_SNAPSHOT,
  }
  private attempt = 0
  private abortController: AbortController | null = null
  private audio: HTMLAudioElement | null = null
  private objectUrl: string | null = null
  private destroyed = false

  constructor(
    private readonly dependencies: VoicePreviewDependencies,
    private readonly events: VoicePreviewEvents,
  ) {}

  get snapshot(): VoicePreviewSnapshot {
    return {
      ...this.snapshotValue,
      timestamps: { ...this.snapshotValue.timestamps },
    }
  }

  async preview(request: VoicePreviewRequest, targetKey?: string): Promise<void> {
    if (this.destroyed) return
    this.release()
    const attempt = ++this.attempt
    const key = targetKey || request.speaker || request.figure_id || 'voice'
    const abortController = new AbortController()
    this.abortController = abortController
    this.publish({
      status: 'synthesizing',
      targetKey: key,
      speaker: request.speaker || '',
      engine: '',
      source: '',
      error: '',
      timestamps: { requested: this.dependencies.now() },
    })

    try {
      const result = await this.dependencies.fetchAudio(
        request,
        abortController.signal,
      )
      if (!this.isCurrent(attempt) || result.blob.size === 0) {
        if (this.isCurrent(attempt)) {
          this.fail('没有收到可播放音频')
        }
        return
      }
      this.publish({
        status: 'transferred',
        speaker: result.speaker || request.speaker || '',
        engine: result.engine,
        source: result.source,
        timestamps: {
          ...this.snapshotValue.timestamps,
          synthesized: Date.parse(result.synthesizedAt) || this.dependencies.now(),
          transferred: Date.parse(result.transferredAt) || this.dependencies.now(),
        },
      })

      const objectUrl = this.dependencies.createObjectURL(result.blob)
      this.objectUrl = objectUrl
      const audio = this.dependencies.createAudio()
      this.audio = audio
      audio.preload = 'auto'
      audio.onloadeddata = () => {
        if (!this.isCurrent(attempt) || this.audio !== audio) return
        this.publish({
          status: 'decoded',
          timestamps: {
            ...this.snapshotValue.timestamps,
            decoded: this.dependencies.now(),
          },
        })
      }
      audio.onplaying = () => {
        if (!this.isCurrent(attempt) || this.audio !== audio) return
        this.publish({
          status: 'playing',
          timestamps: {
            ...this.snapshotValue.timestamps,
            playbackStarted: this.dependencies.now(),
          },
        })
      }
      audio.onended = () => {
        if (!this.isCurrent(attempt) || this.audio !== audio) return
        this.publish({
          status: 'completed',
          timestamps: {
            ...this.snapshotValue.timestamps,
            playbackCompleted: this.dependencies.now(),
          },
        })
        this.releaseAudio()
      }
      audio.onerror = () => {
        if (!this.isCurrent(attempt) || this.audio !== audio) return
        this.fail('音频已传输，但当前设备无法播放')
      }
      audio.src = objectUrl
      audio.load()
      await audio.play()
    } catch (error) {
      if (!this.isCurrent(attempt)) return
      if (error instanceof Error && error.name === 'AbortError') return
      this.fail(error instanceof Error ? error.message : '声线试听失败')
    }
  }

  stop(): void {
    if (this.destroyed && !this.audio && !this.abortController) return
    this.attempt += 1
    this.release()
    this.publish({
      ...INITIAL_VOICE_PREVIEW_SNAPSHOT,
      timestamps: {},
    })
  }

  destroy(): void {
    if (this.destroyed) return
    this.destroyed = true
    this.stop()
  }

  private fail(message: string): void {
    this.release()
    this.publish({
      status: 'error',
      error: message,
    })
  }

  private release(): void {
    this.abortController?.abort()
    this.abortController = null
    this.releaseAudio()
  }

  private releaseAudio(): void {
    const audio = this.audio
    this.audio = null
    if (audio) {
      audio.onloadeddata = null
      audio.onplaying = null
      audio.onended = null
      audio.onerror = null
      audio.pause()
      audio.removeAttribute('src')
      audio.load()
    }
    if (this.objectUrl) {
      this.dependencies.revokeObjectURL(this.objectUrl)
      this.objectUrl = null
    }
  }

  private isCurrent(attempt: number): boolean {
    return !this.destroyed && attempt === this.attempt
  }

  private publish(patch: Partial<VoicePreviewSnapshot>): void {
    this.snapshotValue = { ...this.snapshotValue, ...patch }
    this.events.onState(this.snapshot)
  }
}
