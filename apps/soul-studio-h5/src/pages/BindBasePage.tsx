// pages/BindBasePage.tsx - 屏1：扫码欢迎/绑定（完整状态机）
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiBases, ApiError, BindingStatus } from '../services/api'
import StarField from '../components/StarField'
import LiquidGlassPanel from '../components/LiquidGlassPanel'

type ToastType = { message: string; type: 'info' | 'error' | 'success' } | null

export default function BindBasePage() {
  const navigate = useNavigate()
  
  // 绑定状态机
  const [bindingStatus, setBindingStatus] = useState<BindingStatus>('unbound')
  const [baseId, setBaseId] = useState<string | null>(null)
  const [hasCurrentFigure, setHasCurrentFigure] = useState(false)
  
  // 弹窗状态
  const [showScanModal, setShowScanModal] = useState(false)
  const [showUnbindModal, setShowUnbindModal] = useState(false)
  
  // 操作状态
  const [binding, setBinding] = useState(false)
  const [unbinding, setUnbinding] = useState(false)
  const [qrPayload, setQrPayload] = useState('')
  const [scanning, setScanning] = useState(false)
  const [scannerMessage, setScannerMessage] = useState('')
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const scanTimerRef = useRef<number | null>(null)
  
  // Toast
  const [toast, setToast] = useState<ToastType>(null)

  useEffect(() => {
    let cancelled = false
    apiBases.list()
      .then(bases => {
        if (cancelled) return
        const currentBase = bases[0]
        if (!currentBase) return
        setBaseId(currentBase.base.base_id)
        setBindingStatus('bound_to_current_user')
        setHasCurrentFigure(Boolean(currentBase.figure))
      })
      .catch((error: Error) => showToast(error.message || '底座状态加载失败', 'error'))
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => () => stopScanner(), [])

  // Toast 自动消失
  function showToast(message: string, type: 'info' | 'error' | 'success' = 'info') {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  function stopScanner() {
    if (scanTimerRef.current !== null) {
      window.clearTimeout(scanTimerRef.current)
      scanTimerRef.current = null
    }
    streamRef.current?.getTracks().forEach(track => track.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setScanning(false)
  }

  function closeScanModal() {
    stopScanner()
    setShowScanModal(false)
    setScannerMessage('')
    setQrPayload('')
  }

  async function startScanner() {
    const Detector = (window as unknown as {
      BarcodeDetector?: new (options: { formats: string[] }) => {
        detect(source: HTMLVideoElement): Promise<Array<{ rawValue?: string }>>
      }
    }).BarcodeDetector
    if (!Detector) {
      setScannerMessage('当前浏览器不支持直接扫码，请粘贴二维码内容。')
      return
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setScannerMessage('当前环境无法访问摄像头，请粘贴二维码内容。')
      return
    }
    stopScanner()
    setScanning(true)
    setScannerMessage('请将底座二维码放入取景框')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } },
        audio: false,
      })
      streamRef.current = stream
      const video = videoRef.current
      if (!video) throw new Error('扫码画面初始化失败')
      video.srcObject = stream
      await video.play()
      const detector = new Detector({ formats: ['qr_code'] })
      const scan = async () => {
        if (!streamRef.current || !videoRef.current) return
        try {
          const codes = await detector.detect(videoRef.current)
          const value = codes.find(code => code.rawValue)?.rawValue?.trim()
          if (value) {
            setQrPayload(value)
            stopScanner()
            await handleScanBind(value)
            return
          }
        } catch {
          setScannerMessage('二维码识别失败，请调整距离或粘贴二维码内容。')
        }
        scanTimerRef.current = window.setTimeout(scan, 250)
      }
      void scan()
    } catch (error) {
      stopScanner()
      setScannerMessage(error instanceof Error ? error.message : '无法打开摄像头')
    }
  }

  // 扫码绑定
  async function handleScanBind(qrToken: string) {
    setBinding(true)
    try {
      const result = await apiBases.bind({
        qr_token: qrToken,
      })
      
      if (result.success && result.base_id) {
        setBindingStatus('bound_to_current_user')
        setBaseId(result.base_id)
        setHasCurrentFigure(Boolean(result.base?.active_figure_id))
        closeScanModal()
        showToast('绑定成功', 'success')
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === 'INVALID_QR_CODE') {
        showToast('二维码无效，请扫描灵偶底座上的正确二维码。', 'error')
      } else if (error instanceof ApiError && error.code === 'BASE_ALREADY_BOUND') {
        showToast('该底座已绑定其他账号。', 'error')
      } else if (error instanceof ApiError && error.code === 'ACCOUNT_ALREADY_HAS_BASE') {
        showToast('当前账号已有底座，请先解绑后再配对。', 'error')
      } else {
        showToast(error instanceof Error ? error.message : '绑定失败，请检查网络后重试。', 'error')
      }
    } finally {
      setBinding(false)
    }
  }

  // 解绑
  async function handleUnbind() {
    if (!baseId) return
    setUnbinding(true)
    try {
      const result = await apiBases.unbind({
        base_id: baseId,
      })
      
      if (result.success) {
        setBindingStatus('unbound')
        setBaseId(null)
        setHasCurrentFigure(false)
        setShowUnbindModal(false)
        showToast('已解绑底座，可重新扫码绑定', 'success')
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : '解绑失败，请检查网络后重试。', 'error')
    } finally {
      setUnbinding(false)
    }
  }

  // 点击"开始创建灵魂"
  function handleStartCreate() {
    if (bindingStatus === 'unbound') {
      showToast('未绑定底座，请先扫码绑定底座。', 'error')
      setShowScanModal(true)
    } else if (bindingStatus === 'bound_to_current_user') {
      navigate(hasCurrentFigure ? '/home' : '/create')
    }
  }

  // 点击"绑定到底座"
  function handleBindButton() {
    if (bindingStatus === 'unbound') {
      setShowScanModal(true)
    } else if (bindingStatus === 'bound_to_current_user') {
      showToast(`当前已绑定 ${baseId}。`, 'info')
    }
  }

  return (
    <div className="min-h-screen bg-castle relative overflow-hidden">
      <StarField count={40} />
      <div className="pointer-events-none absolute -top-28 left-1/2 h-80 w-80 -translate-x-1/2 rounded-full bg-white/64 blur-3xl" />
      <div className="pointer-events-none absolute bottom-20 -right-24 h-64 w-64 rounded-full bg-violet-200/24 blur-3xl" />

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

      <div className="relative z-10 flex min-h-screen flex-col items-center px-5 pb-8 pt-14">
        {/* 标题区 */}
        <div className="mb-6 text-center">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-white/60 px-3 py-1 text-[10px] font-semibold tracking-[0.25em] text-purple-400 ring-1 ring-white/70">
            ✦ SOUL STUDIO ✦
          </div>
          <h1 className="text-5xl font-black tracking-wider text-soul-gradient" style={{ fontFamily: 'serif' }}>
            灵偶
          </h1>
          <p className="mt-3 text-sm font-semibold text-purple-600">先连接底座，再召唤你的灵偶伙伴</p>
          <p className="mt-1 text-xs font-medium text-purple-400">扫码配对 · 创建灵魂 · 开始互动</p>
        </div>

        {/* 中央玻璃罩 + 角色 + 底座 */}
        <div className="relative my-4 flex flex-col items-center">
          {/* 旋转光圈 */}
          <div className="absolute top-12 left-1/2 -translate-x-1/2 w-56 h-56 rounded-full border border-purple-200/40 spin-slow pointer-events-none" />
          <div className="absolute top-20 left-1/2 -translate-x-1/2 w-44 h-44 rounded-full border border-pink-200/40 spin-slow pointer-events-none" style={{ animationDirection: 'reverse', animationDuration: '15s' }} />

          {/* 玻璃罩 */}
          <div className="dome-glass relative flex items-end justify-center pb-6">
            {/* 角色剪影占位 */}
            <div className="relative ritual-glow">
              <div
                className="w-24 h-32 rounded-full bg-gradient-to-br from-white/80 via-indigo-100/70 to-violet-100/70"
                style={{
                  filter: 'blur(1px)',
                  boxShadow: '0 0 40px rgba(196, 181, 253, 0.8), inset 0 0 20px rgba(255, 255, 255, 0.4)',
                }}
              />
              <div className="absolute inset-0 flex items-center justify-center text-3xl">✨</div>
            </div>
            {/* 装饰星点 */}
            <span className="absolute top-4 left-6 text-yellow-300 twinkle text-lg">✦</span>
            <span className="absolute top-12 right-8 text-yellow-300 twinkle text-sm" style={{ animationDelay: '0.5s' }}>✧</span>
            <span className="absolute bottom-16 left-10 text-yellow-300 twinkle text-xs" style={{ animationDelay: '1s' }}>✦</span>
          </div>
          {/* 底座 */}
          <div className="dome-base" />
        </div>

        {/* 底座状态卡 */}
        <LiquidGlassPanel
          className="mt-4 mb-6 w-full max-w-sm"
          contentClassName="p-5"
          radius={30}
          variant="hero"
        >
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-bold text-purple-500">
              {bindingStatus === 'unbound' ? '未绑定底座' : '已绑定底座'}
            </span>
            {bindingStatus === 'bound_to_current_user' && (
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-green-300 to-green-500 text-xs text-white shadow-md">
                ✓
              </div>
            )}
          </div>
          <p className="mb-1 text-2xl font-black text-soul-gradient">
            {bindingStatus === 'unbound' ? '绑定灵偶底座' : baseId}
          </p>
          <p className="mb-4 text-xs font-semibold text-purple-400">
            {bindingStatus === 'unbound' ? '扫描底座二维码后，才会把灵偶绑定到你的设备。' : '底座已就绪。'}
          </p>
          {/* 底座占位图 */}
          <div className="flex justify-center">
            <div
              className="w-24 h-20 rounded-t-3xl bg-gradient-to-b from-white/90 via-indigo-100/80 to-violet-200/70 relative"
              style={{ boxShadow: '0 12px 28px rgba(63, 73, 132, 0.12), inset 0 2px 0 rgba(255, 255, 255, 0.72)' }}
            >
              <div className="absolute top-3 left-1/2 -translate-x-1/2 w-12 h-12 bg-white/80 rounded grid grid-cols-3 gap-px p-1">
                {Array.from({ length: 9 }).map((_, i) => (
                  <div key={i} className="bg-purple-700/80" />
                ))}
              </div>
              <div className="absolute bottom-2 left-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-yellow-300 twinkle" />
            </div>
          </div>
          
          {/* 解绑入口 - 仅已绑定时显示 */}
          {bindingStatus === 'bound_to_current_user' && (
            <button
              onClick={() => setShowUnbindModal(true)}
              className="mx-auto mt-4 flex items-center gap-1 rounded-full bg-purple-50 px-3 py-1.5 text-xs font-bold text-purple-500 transition-colors hover:text-purple-700"
            >
              <span>更换 / 解绑底座</span>
              <span>›</span>
            </button>
          )}
        </LiquidGlassPanel>

        {/* 主按钮 */}
        <button
          onClick={bindingStatus === 'unbound' ? handleBindButton : handleStartCreate}
          disabled={binding}
          className="btn-soul flex w-full max-w-sm items-center justify-center gap-2 text-base"
        >
          <span>✦</span>
          <span>
            {binding
              ? '绑定中…'
              : bindingStatus === 'bound_to_current_user'
                ? hasCurrentFigure ? '返回当前灵偶' : '开始创建灵偶'
                : '扫码绑定底座'}
          </span>
          <span>✦</span>
        </button>

        {/* 次按钮 */}
        <button
          onClick={bindingStatus === 'unbound' ? handleStartCreate : handleBindButton}
          disabled={binding}
          className="btn-soul-secondary mt-3 w-full max-w-sm text-base"
        >
          {binding ? '绑定中…' : 
           bindingStatus === 'bound_to_current_user' ? `已绑定 ${baseId}` : 
           '绑定后创建灵偶'}
        </button>

        {/* 底部小字 */}
        <p className="mt-auto flex items-center gap-1 pt-6 text-center text-xs text-purple-400">
          请确保底座已通电并靠近手机
          <span className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full border border-purple-300 text-[10px]">ⓘ</span>
        </p>
      </div>

      {/* 扫码弹窗 */}
      {showScanModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={closeScanModal} />
          <div className="relative w-full max-w-sm animate-fade-in overflow-hidden rounded-[30px] bg-white/92 p-6 shadow-soul-lg ring-1 ring-white/80">
            <div className="absolute -right-12 -top-12 h-32 w-32 rounded-full bg-purple-200/40 blur-2xl" />
            <div className="relative">
            <h3 className="mb-2 text-center text-lg font-black text-soul-gradient">扫描底座二维码</h3>
            <p className="mb-4 text-center text-sm text-purple-500">请扫描灵偶底座上的二维码完成配对</p>

            <div className="relative mb-4 h-44 w-full overflow-hidden rounded-3xl bg-slate-950">
              <video
                ref={videoRef}
                muted
                playsInline
                className={`h-full w-full object-cover ${scanning ? 'opacity-100' : 'opacity-0'}`}
              />
              {!scanning && (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                  <span className="text-4xl text-purple-200">⌗</span>
                  <p className="mt-2 text-xs font-semibold text-purple-100">摄像头尚未开启</p>
                </div>
              )}
              <div className="pointer-events-none absolute inset-5 rounded-2xl border border-white/70 shadow-[0_0_0_999px_rgba(15,23,42,0.18)]" />
            </div>

            <p className="mb-3 min-h-4 text-center text-xs text-purple-500">
              {scannerMessage || '二维码仅用于认领底座，不包含设备事件凭据。'}
            </p>

            <div className="mb-4 space-y-2">
              <button
                type="button"
                onClick={scanning ? stopScanner : startScanner}
                disabled={binding}
                className="w-full rounded-2xl bg-purple-600 py-2.5 text-sm font-bold text-white transition-colors hover:bg-purple-700 disabled:opacity-50"
              >
                {scanning ? '关闭摄像头' : '打开摄像头扫码'}
              </button>
              <div className="flex items-center gap-2 py-1 text-[11px] font-semibold text-purple-300">
                <span className="h-px flex-1 bg-purple-100" />
                <span>或粘贴二维码内容</span>
                <span className="h-px flex-1 bg-purple-100" />
              </div>
              <input
                value={qrPayload}
                onChange={event => setQrPayload(event.target.value)}
                placeholder="lingou://pair?token=..."
                autoCapitalize="none"
                autoCorrect="off"
                className="w-full rounded-2xl border border-purple-100 bg-white/80 px-3 py-2.5 text-sm text-purple-800 outline-none focus:border-purple-300"
              />
              <button
                type="button"
                onClick={() => handleScanBind(qrPayload.trim())}
                disabled={binding || !qrPayload.trim()}
                className="w-full rounded-2xl bg-purple-100 py-2.5 text-sm font-bold text-purple-700 transition-colors hover:bg-purple-200 disabled:opacity-50"
              >
                {binding ? '正在验证并绑定…' : '验证并绑定'}
              </button>
            </div>
            
            {/* 取消按钮 */}
            <button
              onClick={closeScanModal}
              className="w-full rounded-2xl border border-purple-100 bg-white/70 py-2.5 text-sm font-bold text-purple-600 transition-colors hover:bg-white/90"
            >
              取消
            </button>
            </div>
          </div>
        </div>
      )}

      {/* 解绑确认弹窗 */}
      {showUnbindModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowUnbindModal(false)} />
          <div className="relative w-full max-w-sm animate-fade-in overflow-hidden rounded-[30px] bg-white/92 p-6 shadow-soul-lg ring-1 ring-white/80">
            <h3 className="mb-3 text-center text-lg font-black text-soul-gradient">确认解绑底座？</h3>
            <p className="mb-6 text-center text-sm leading-relaxed text-purple-600">
              解绑后，当前灵偶将不再与 {baseId} 关联。<br />
              你可以重新扫码绑定新的底座。<br />
              <span className="text-purple-500">解绑不会删除灵偶档案。</span>
            </p>
            
            <div className="flex gap-3">
              <button
                onClick={() => setShowUnbindModal(false)}
                className="flex-1 rounded-2xl border border-purple-100 bg-white/70 py-2.5 text-sm font-bold text-purple-600 transition-colors hover:bg-white/90"
              >
                取消
              </button>
              <button
                onClick={handleUnbind}
                disabled={unbinding}
                className="flex-1 rounded-2xl bg-red-500 py-2.5 text-sm font-bold text-white transition-colors hover:bg-red-600 disabled:opacity-50"
              >
                {unbinding ? '解绑中…' : '确认解绑'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
