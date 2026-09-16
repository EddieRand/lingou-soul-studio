import { useMemo, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../context/AuthContext'
import { getPostLoginPath } from '../utils/onboarding'

type LoginViewState = 'cover' | 'loginSheet' | 'loggingIn'

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

function Toast({ message }: { message: string }) {
  if (!message) return null
  return <div className="login-toast" role="status">{message}</div>
}

interface GlassLoginSheetProps {
  agreed: boolean
  username: string
  password: string
  loggingIn: boolean
  onUsernameChange: (value: string) => void
  onPasswordChange: (value: string) => void
  onToggleAgree: () => void
  onSubmit: (event: React.FormEvent) => void
  onProtocol: (type: 'user' | 'privacy') => void
}

function GlassLoginSheet({
  agreed,
  username,
  password,
  loggingIn,
  onUsernameChange,
  onPasswordChange,
  onToggleAgree,
  onSubmit,
  onProtocol,
}: GlassLoginSheetProps) {
  return (
    <section className="login-sheet" onClick={event => event.stopPropagation()} aria-label="账号登录面板">
      <div className="login-sheet-heading">
        <p>欢迎回来</p>
        <span>使用你的灵偶账号继续</span>
      </div>

      <form className="login-account-form" onSubmit={onSubmit}>
        <label>
          <span>用户名或邮箱</span>
          <input
            type="text"
            value={username}
            onChange={event => onUsernameChange(event.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            disabled={loggingIn}
            required
          />
        </label>
        <label>
          <span>密码</span>
          <input
            type="password"
            value={password}
            onChange={event => onPasswordChange(event.target.value)}
            autoComplete="current-password"
            disabled={loggingIn}
            required
          />
        </label>

        <button type="submit" className="login-account-submit" disabled={loggingIn}>
          <span>{loggingIn ? '正在登录…' : '登录'}</span>
          {loggingIn && <span className="login-button-spinner" />}
        </button>
      </form>

      <p className="login-register-link">
        还没有账号？<Link to="/register">创建账号</Link>
      </p>

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
  const location = useLocation()
  const { login } = useAuth()
  const [viewState, setViewState] = useState<LoginViewState>('cover')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [agreed, setAgreed] = useState(false)
  const [toast, setToast] = useState('')

  const coverOnly = viewState === 'cover'
  const showSheet = viewState === 'loginSheet' || viewState === 'loggingIn'
  const statusText = useMemo(() => (
    viewState === 'loggingIn' ? '正在进入 Soul Studio…' : '轻触屏幕，进入 Soul Studio'
  ), [viewState])

  function showToast(message: string) {
    setToast(message)
    window.setTimeout(() => setToast(current => (current === message ? '' : current)), 2400)
  }

  function handlePageClick() {
    if (viewState === 'cover') {
      setViewState('loginSheet')
    } else if (viewState === 'loginSheet') {
      setViewState('cover')
    }
  }

  async function handleLogin(event: React.FormEvent) {
    event.preventDefault()
    if (viewState === 'loggingIn') return
    if (!agreed) {
      showToast('请先阅读并同意用户协议和隐私政策')
      return
    }
    if (!username.trim() || !password) {
      showToast('请输入用户名和密码')
      return
    }

    setViewState('loggingIn')
    try {
      await login(username.trim(), password)
      const requestedPath = (location.state as { from?: string } | null)?.from
      const destination = requestedPath?.startsWith('/') ? requestedPath : getPostLoginPath()
      navigate(destination, { replace: true })
    } catch (error) {
      showToast(error instanceof Error ? error.message : '登录失败，请重试')
      setViewState('loginSheet')
    }
  }

  function handleProtocol(type: 'user' | 'privacy') {
    showToast(type === 'user' ? '用户协议暂未接入' : '隐私政策暂未接入')
  }

  return (
    <main className={`login-page ${showSheet ? 'login-page--sheet-open' : ''}`} onClick={handlePageClick}>
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
            username={username}
            password={password}
            loggingIn={viewState === 'loggingIn'}
            onUsernameChange={setUsername}
            onPasswordChange={setPassword}
            onToggleAgree={() => setAgreed(value => !value)}
            onSubmit={handleLogin}
            onProtocol={handleProtocol}
          />
        )}

        <Toast message={toast} />
      </section>
    </main>
  )
}
