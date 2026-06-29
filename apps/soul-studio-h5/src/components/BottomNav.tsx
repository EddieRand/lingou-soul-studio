// components/BottomNav.tsx - 全局底部导航栏
import { useEffect, useRef, useState, type MouseEvent, type PointerEvent } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import LiquidGlassPanel from './LiquidGlassPanel'

const TABS = [
  { path: '/home', label: '我的灵偶', icon: '🏠' },
  { path: '/simulate', label: '互动', icon: '🎮' },
  { path: '/dialogue-debug', label: '对话', icon: '💬' },
]

const LONG_PRESS_MS = 260

type DragState = {
  startX: number
  currentX: number
  startIndex: number
  targetIndex: number
}

export default function BottomNav() {
  const navigate = useNavigate()
  const location = useLocation()
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([])
  const longPressTimerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null)
  const pointerStartRef = useRef<{ x: number; y: number; index: number } | null>(null)
  const suppressClickRef = useRef(false)
  const [dragState, setDragState] = useState<DragState | null>(null)

  const activeIndex = TABS.findIndex(tab =>
    location.pathname === tab.path ||
    (tab.path !== '/home' && location.pathname.startsWith(tab.path))
  )

  useEffect(() => {
    return () => clearLongPressTimer()
  }, [])

  // 隐藏导航的页面（绑定页、创建向导等全屏页面）
  const hideOn = ['/bind', '/create']
  if (hideOn.some(p => location.pathname.startsWith(p))) {
    return null
  }

  function clearLongPressTimer() {
    if (longPressTimerRef.current) {
      window.clearTimeout(longPressTimerRef.current)
      longPressTimerRef.current = null
    }
  }

  function getTargetIndex(clientX: number) {
    let nextIndex = activeIndex >= 0 ? activeIndex : 0
    let minDistance = Number.POSITIVE_INFINITY

    buttonRefs.current.forEach((button, index) => {
      if (!button) return
      const rect = button.getBoundingClientRect()
      const centerX = rect.left + rect.width / 2
      const distance = Math.abs(clientX - centerX)
      if (distance < minDistance) {
        minDistance = distance
        nextIndex = index
      }
    })

    return nextIndex
  }

  function getDragOffset(index: number) {
    if (!dragState || dragState.startIndex !== index) return 0

    const startButton = buttonRefs.current[dragState.startIndex]
    const firstButton = buttonRefs.current[0]
    const lastButton = buttonRefs.current[TABS.length - 1]
    if (!startButton || !firstButton || !lastButton) {
      return dragState.currentX - dragState.startX
    }

    const startRect = startButton.getBoundingClientRect()
    const firstRect = firstButton.getBoundingClientRect()
    const lastRect = lastButton.getBoundingClientRect()
    const startCenter = startRect.left + startRect.width / 2
    const minOffset = firstRect.left + firstRect.width / 2 - startCenter
    const maxOffset = lastRect.left + lastRect.width / 2 - startCenter
    const rawOffset = dragState.currentX - dragState.startX

    return Math.max(minOffset, Math.min(maxOffset, rawOffset))
  }

  function resetDrag(suppressClick = false) {
    clearLongPressTimer()
    pointerStartRef.current = null
    setDragState(null)

    if (suppressClick) {
      suppressClickRef.current = true
      window.setTimeout(() => {
        suppressClickRef.current = false
      }, 80)
    }
  }

  function handlePointerDown(index: number, event: PointerEvent<HTMLButtonElement>) {
    if (index !== activeIndex) return

    pointerStartRef.current = { x: event.clientX, y: event.clientY, index }
    event.currentTarget.setPointerCapture(event.pointerId)

    clearLongPressTimer()
    longPressTimerRef.current = window.setTimeout(() => {
      const start = pointerStartRef.current
      if (!start) return

      suppressClickRef.current = true
      setDragState({
        startX: start.x,
        currentX: start.x,
        startIndex: start.index,
        targetIndex: start.index,
      })
    }, LONG_PRESS_MS)
  }

  function handlePointerMove(event: PointerEvent<HTMLButtonElement>) {
    const start = pointerStartRef.current
    if (!start) return

    if (!dragState) {
      const dx = event.clientX - start.x
      const dy = event.clientY - start.y
      if (Math.abs(dy) > 18 && Math.abs(dy) > Math.abs(dx) * 1.4) {
        resetDrag(false)
      }
      return
    }

    event.preventDefault()
    const targetIndex = getTargetIndex(event.clientX)
    setDragState({
      ...dragState,
      currentX: event.clientX,
      targetIndex,
    })
  }

  function handlePointerEnd(event: PointerEvent<HTMLButtonElement>) {
    clearLongPressTimer()

    if (!dragState) {
      pointerStartRef.current = null
      return
    }

    event.preventDefault()
    const targetIndex = getTargetIndex(event.clientX)
    const targetTab = TABS[targetIndex]
    resetDrag(true)

    if (targetTab && targetIndex !== activeIndex) {
      navigate(targetTab.path)
    }
  }

  function handleClick(path: string, event: MouseEvent<HTMLButtonElement>) {
    if (suppressClickRef.current) {
      event.preventDefault()
      event.stopPropagation()
      return
    }

    navigate(path)
  }

  return (
    <div className="bottom-nav-shell fixed left-0 right-0 z-30 px-4 pt-6">
      <LiquidGlassPanel
        className="mx-auto max-w-lg"
        contentClassName="relative flex p-1.5"
        radius={28}
        variant="nav"
      >
          {activeIndex >= 0 && (
            <div
              className={`bottom-nav-indicator liquid-droplet liquid-droplet--nav ${dragState ? 'bottom-nav-indicator--dragging' : ''}`}
              style={{
                transform: `translateX(calc(${(dragState?.startIndex ?? activeIndex) * 100}% + ${dragState ? getDragOffset(dragState.startIndex) : 0}px)) ${dragState ? 'scale(1.04)' : 'scale(1)'}`,
                transition: dragState ? 'none' : undefined,
              }}
            >
              <span className="bottom-nav-indicator__dot" />
            </div>
          )}

          {TABS.map((tab, index) => {
            const active = location.pathname === tab.path ||
              (tab.path !== '/home' && location.pathname.startsWith(tab.path))
            const isDragging = dragState?.startIndex === index
            const visualActive = dragState ? dragState.targetIndex === index : active

            return (
              <button
                key={tab.path}
                ref={element => {
                  buttonRefs.current[index] = element
                }}
                onClick={event => handleClick(tab.path, event)}
                onPointerDown={event => handlePointerDown(index, event)}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerEnd}
                onPointerCancel={() => resetDrag(true)}
                className={`bottom-nav-tab relative flex flex-1 flex-col items-center gap-1 rounded-[22px] py-2.5 transition-all ${
                  visualActive
                    ? `bottom-nav-tab--active text-purple-950 ${isDragging ? 'bottom-nav-tab--dragging' : ''}`
                    : 'text-purple-500 hover:text-purple-800'
                }`}
              >
                <span className="text-xl">{tab.icon}</span>
                <span className="text-[11px] font-bold">
                  {tab.label}
                </span>
              </button>
            )
          })}
      </LiquidGlassPanel>
    </div>
  )
}
