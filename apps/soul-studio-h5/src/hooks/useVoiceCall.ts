import { useCallback, useEffect, useRef, useState } from 'react'
import { apiAuth } from '../services/api'
import {
  INITIAL_VOICE_CALL_SNAPSHOT,
  VoiceCallController,
  type VoiceCallSnapshot,
  type VoiceServerMessage,
} from '../services/voiceCallController'

interface UseVoiceCallOptions {
  onServerMessage(message: VoiceServerMessage): void
}

interface UseVoiceCallResult {
  snapshot: VoiceCallSnapshot
  start(baseId: string): Promise<void>
  stop(reason?: string): void
}

export function useVoiceCall({
  onServerMessage,
}: UseVoiceCallOptions): UseVoiceCallResult {
  const [snapshot, setSnapshot] = useState<VoiceCallSnapshot>(
    INITIAL_VOICE_CALL_SNAPSHOT,
  )
  const mountedRef = useRef(true)
  const messageHandlerRef = useRef(onServerMessage)
  messageHandlerRef.current = onServerMessage

  const controllerRef = useRef<VoiceCallController | null>(null)
  if (!controllerRef.current) {
    controllerRef.current = new VoiceCallController(
      {
        getUserMedia: constraints => navigator.mediaDevices.getUserMedia(constraints),
        createAudioContext: () => new AudioContext(),
        createWebSocket: (url, protocols) => new WebSocket(url, protocols),
        createTicket: baseId => apiAuth.createWebSocketTicket(baseId),
        websocketUrl: baseId => {
          const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
          return `${protocol}//${window.location.host}/api/asr/stream?base_id=${encodeURIComponent(baseId)}`
        },
        setTimer: (callback, delayMs) => window.setTimeout(callback, delayMs),
        clearTimer: timerId => window.clearTimeout(timerId),
      },
      {
        onState: next => {
          if (mountedRef.current) setSnapshot(next)
        },
        onServerMessage: message => {
          if (mountedRef.current) messageHandlerRef.current(message)
        },
      },
    )
  }

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      queueMicrotask(() => {
        // React StrictMode immediately re-runs effects after a simulated
        // cleanup. Only a real unmount remains inactive by the next microtask.
        if (!mountedRef.current) controllerRef.current?.destroy()
      })
    }
  }, [])

  const start = useCallback((baseId: string) => {
    return controllerRef.current?.start(baseId) || Promise.resolve()
  }, [])

  const stop = useCallback((reason?: string) => {
    controllerRef.current?.stop(reason)
  }, [])

  return { snapshot, start, stop }
}
