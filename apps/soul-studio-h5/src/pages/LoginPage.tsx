import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiAuth } from '../services/api'
import { useAuth } from '../context/AuthContext'
import { getPostLoginPath } from '../utils/onboarding'

type LoginViewState = 'cover' | 'loginSheet' | 'loggingIn'
type LoginProvider = 'wechat' | 'apple'

const stars = Array.from({ length: 18 }).map((_, index) => ({
  id: index,
  left: [8, 16, 28, 39, 52, 64, 78, 89, 12, 23, 44, 57, 71, 84, 34, 47, 66, 92][index],
  top: [12, 28, 18, 9, 24, 14, 31, 21, 54, 43, 62, 49, 57, 66, 78, 72, 83, 76][index],
  size: [2, 1.2, 1.8, 1, 2.4, 1.4, 2, 1.1, 1.6, 1, 1.8, 1.2, 2.2, 1.5, 1, 1.7, 1.3, 2][index],
  delay: [0, 1.1, 2.2, 3.1, 0.6, 1.8, 2.7, 3.5, 0.3, 1.4, 2.5, 3.8, 0.9, 1.9, 2.9, 0.2, 1.6, 3.2][index],
  duration: [3.8, 4.6, 5.2, 4.1, 5.8, 4.9, 6.2, 4.4, 5.5, 4.2, 6, 5, 4.8, 5.6, 4.5, 6.4, 5.1, 4.7][index],
}))

const butterflies = [
  { id: 1, left: 12, top: 36, scale: 0.82, delay: 0, duration: 13 },
  { id: 2, left: 78, top: 31, scale: 0.72, delay: 1.4, duration: 16 },
  { id: 3, left: 18, top: 69, scale: 0.68, delay: 2.2, duration: 18 },
  { id: 4, left: 72, top: 62, scale: 0.9, delay: 0.8, duration: 15 },
  { id: 5, left: 45, top: 76, scale: 0.58, delay: 3, duration: 20 },
]

function LoginStarField() {
  return (
    <div className="login-star-field" aria-hidden="true">
      {stars.map(star => (
        <span
          key={star.id}
          className="login-star"
          style={{
            left: `${star.left}%`,
            top: `${star.top}%`,
            width: `${star.size}px`,
            height: `${star.size}px`,
            animationDelay: `${star.delay}s`,
            animationDuration: `${star.duration}s`,
          }}
        />
      ))}
    </div>
  )
}

function ButterflyIcon() {
  return (
    <svg viewBox="0 0 48 42" className="login-butterfly__svg" focusable="false" aria-hidden="true">
      <path d="M23.7 20.3C19 8.7 10.1 1.4 5.3 4.6.3 8 .3 19.2 7.1 24.4c4.3 3.3 10.8 1.6 15.2-2.5-3 5.7-5 13.8-1 16.1 4.9 2.8 12-5.2 8.9-14.2 4.7 5 11.6 7.2 15.1 2.8 4.9-6.1.4-16.6-5.2-18.3-5.2-1.6-11.1 4.2-14.1 12.1.1-8-2-15.4-6.4-15.4-4 0-4.6 7.2 4.1 15.3Z" />
      <path d="M24.1 18.2c1.6 5.3 1.2 12.1-.9 17.3" />
    </svg>
  )
}

function AnimatedButterflies() {
  return (
    <div className="login-butterflies" aria-hidden="true">
      {butterflies.map(item => (
        <span
          key={item.id}
          className="login-butterfly"
          style={{
            left: `${item.left}%`,
            top: `${item.top}%`,
            scale: `${item.scale}`,
            animationDelay: `${item.delay}s`,
            animationDuration: `${item.duration}s`,
          }}
        >
          <ButterflyIcon />
        </span>
      ))}
    </div>
  )
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="none" aria-hidden="true">
      <path d="M4.5 10.3 8.1 14 15.7 6" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function WechatIcon() {
  return (
    <svg viewBox="0 0 32 32" className="h-6 w-6" fill="currentColor" aria-hidden="true">
      <path d="M12.6 6.1C7.3 6.1 3 9.7 3 14.2c0 2.4 1.3 4.6 3.4 6.1l-.8 2.6 3-1.5c1.2.4 2.5.7 4 .7h.6a7.8 7.8 0 0 1-.4-2.4c0-4.3 3.9-7.9 8.7-8.2-1.1-3.1-4.6-5.4-8.9-5.4Zm-3.4 4.5a1.3 1.3 0 1 1 0 2.6 1.3 1.3 0 0 1 0-2.6Zm6.3 0a1.3 1.3 0 1 1 0 2.6 1.3 1.3 0 0 1 0-2.6Z" />
      <path d="M22.1 13.1c-4 0-7.2 2.8-7.2 6.2s3.2 6.2 7.2 6.2c1 0 2-.2 2.9-.5l2.3 1.2-.6-2c1.6-1.2 2.6-2.9 2.6-4.9 0-3.4-3.2-6.2-7.2-6.2Zm-2.3 3.5a1.1 1.1 0 1 1 0 2.1 1.1 1.1 0 0 1 0-2.1Zm5 0a1.1 1.1 0 1 1 0 2.1 1.1 1.1 0 0 1 0-2.1Z" />
    </svg>
  )
}

function AppleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6" fill="currentColor" aria-hidden="true">
      <path d="M18.7 19.5c-.8 1.2-1.7 2.4-3 2.5-1.4 0-1.8-.8-3.3-.8s-2 .8-3.3.8c-1.3.1-2.3-1.3-3.1-2.5-1.7-2.5-3-7.1-1.3-10.1.9-1.5 2.4-2.5 4.1-2.5 1.3 0 2.5.9 3.3.9.8 0 2.3-1.1 3.8-.9.7 0 2.5.3 3.6 2-.1.1-2.2 1.3-2.1 3.8 0 3 2.6 4 2.7 4-.1.1-.4 1.5-1.4 2.8ZM13 3.5C13.7 2.7 14.9 2 15.9 2c.1 1.2-.3 2.4-1 3.2-.7.9-1.8 1.5-3 1.4-.1-1.1.4-2.3 1.1-3.1Z" />
    </svg>
  )
}

function Toast({ message }: { message: string }) {
  if (!message) return null
  return <div className="login-toast" role="status">{message}</div>
}

interface GlassLoginSheetProps {
  agreed: boolean
  viewState: LoginViewState
  provider: LoginProvider | null
  onToggleAgree: () => void
  onLogin: (provider: LoginProvider) => void
  onProtocol: (type: 'user' | 'privacy') => void
}

function GlassLoginSheet({
  agreed,
  viewState,
  provider,
  onToggleAgree,
  onLogin,
  onProtocol,
}: GlassLoginSheetProps) {
  const loggingIn = viewState === 'loggingIn'

  return (
    <section className="login-sheet" onClick={event => event.stopPropagation()} aria-label="登录面板">
      <button
        type="button"
        className="login-oauth-button login-oauth-button--wechat"
        onClick={() => onLogin('wechat')}
        disabled={loggingIn}
      >
        <WechatIcon />
        <span>{loggingIn && provider === 'wechat' ? '正在唤起微信...' : '微信登录'}</span>
        {loggingIn && provider === 'wechat' && <span className="login-button-spinner" />}
      </button>

      <button
        type="button"
        className="login-oauth-button login-oauth-button--apple"
        onClick={() => onLogin('apple')}
        disabled={loggingIn}
      >
        <AppleIcon />
        <span>{loggingIn && provider === 'apple' ? '正在唤起 Apple...' : 'Apple 登录'}</span>
        {loggingIn && provider === 'apple' && <span className="login-button-spinner login-button-spinner--dark" />}
      </button>

      <div className="login-agreement">
        <button
          type="button"
          className={`login-check ${agreed ? 'login-check--checked' : ''}`}
          onClick={onToggleAgree}
          aria-label={agreed ? '取消同意协议' : '同意协议'}
        >
          {agreed && <CheckIcon />}
        </button>
        <p>
          我已阅读并同意
          <button type="button" onClick={() => onProtocol('user')}>《用户协议》</button>
          和
          <button type="button" onClick={() => onProtocol('privacy')}>《隐私政策》</button>
        </p>
      </div>
    </section>
  )
}

export default function LoginPage() {
  const navigate = useNavigate()
  const { refresh } = useAuth()
  const [viewState, setViewState] = useState<LoginViewState>('cover')
  const [agreed, setAgreed] = useState(false)
  const [toast, setToast] = useState('')
  const [provider, setProvider] = useState<LoginProvider | null>(null)

  const coverOnly = viewState === 'cover'
  const showSheet = viewState === 'loginSheet' || viewState === 'loggingIn'
  const statusText = useMemo(() => {
    if (viewState === 'loggingIn') return '正在进入 Soul Studio...'
    return '轻触屏幕，进入 Soul Studio'
  }, [viewState])

  function showToast(message: string) {
    setToast(message)
    window.setTimeout(() => setToast(current => (current === message ? '' : current)), 1800)
  }

  function handlePageClick() {
    if (viewState === 'cover') {
      setViewState('loginSheet')
      return
    }
    if (viewState === 'loginSheet') {
      setViewState('cover')
    }
  }

  async function handleLogin(nextProvider: LoginProvider) {
    if (viewState === 'loggingIn') return

    if (!agreed) {
      showToast('请先阅读并同意用户协议和隐私政策')
      return
    }

    setProvider(nextProvider)
    setViewState('loggingIn')
    showToast(nextProvider === 'wechat' ? '正在唤起微信登录…' : '正在唤起 Apple 登录…')

    try {
      const result = nextProvider === 'wechat'
        ? await apiAuth.wechatLogin()
        : await apiAuth.appleLogin()

      localStorage.setItem('lingou_token', result.access_token)
      localStorage.setItem('lingou_user_id', result.user_id)
      localStorage.setItem('lingou_username', result.username)

      // 更新 AuthContext 状态
      await refresh()

      showToast('登录成功')
      window.setTimeout(() => navigate(getPostLoginPath(), { replace: true }), 600)
    } catch (e: any) {
      showToast(e.message || '登录失败，请重试')
      setViewState('loginSheet')
      setProvider(null)
    }
  }

  function handleProtocol(type: 'user' | 'privacy') {
    console.log(type === 'user' ? '用户协议' : '隐私政策')
    showToast(type === 'user' ? '用户协议暂未接入' : '隐私政策暂未接入')
  }

  return (
    <main
      className={`login-page ${showSheet ? 'login-page--sheet-open' : ''}`}
      onClick={handlePageClick}
    >
      <section className="login-phone-shell" aria-label="灵偶登录页">
        <div className="login-bg" />
        <div className="login-vignette" />
        <LoginStarField />
        <AnimatedButterflies />

        <div className={`login-cover-hint ${coverOnly ? 'login-cover-hint--visible' : ''}`}>
          <span className="login-cover-hint__spark">✦</span>
          <span>{statusText}</span>
        </div>

        {showSheet && (
          <GlassLoginSheet
            agreed={agreed}
            viewState={viewState}
            provider={provider}
            onToggleAgree={() => setAgreed(value => !value)}
            onLogin={handleLogin}
            onProtocol={handleProtocol}
          />
        )}

        <Toast message={toast} />
      </section>
    </main>
  )
}
