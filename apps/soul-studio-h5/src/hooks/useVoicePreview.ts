import { useCallback, useEffect, useRef, useState } from 'react'
import { apiVoice, type VoicePreviewRequest } from '../services/api'
import {
  INITIAL_VOICE_PREVIEW_SNAPSHOT,
  VoicePreviewController,
  type VoicePreviewSnapshot,
} from '../services/voicePreviewController'

interface UseVoicePreviewResult {
  snapshot: VoicePreviewSnapshot
  preview(request: VoicePreviewRequest, targetKey?: string): Promise<void>
  stop(): void
}

export function useVoicePreview(): UseVoicePreviewResult {
  const [snapshot, setSnapshot] = useState<VoicePreviewSnapshot>(
    INITIAL_VOICE_PREVIEW_SNAPSHOT,
  )
  const mountedRef = useRef(true)
  const controllerRef = useRef<VoicePreviewController | null>(null)

  if (!controllerRef.current) {
    controllerRef.current = new VoicePreviewController(
      {
        fetchAudio: (request, signal) => apiVoice.preview(request, signal),
        createAudio: () => new Audio(),
        createObjectURL: blob => URL.createObjectURL(blob),
        revokeObjectURL: url => URL.revokeObjectURL(url),
        now: () => Date.now(),
      },
      {
        onState: next => {
          if (mountedRef.current) setSnapshot(next)
        },
      },
    )
  }

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      queueMicrotask(() => {
        if (!mountedRef.current) controllerRef.current?.destroy()
      })
    }
  }, [])

  const preview = useCallback((request: VoicePreviewRequest, targetKey?: string) => {
    return controllerRef.current?.preview(request, targetKey) || Promise.resolve()
  }, [])

  const stop = useCallback(() => {
    controllerRef.current?.stop()
  }, [])

  return { snapshot, preview, stop }
}
