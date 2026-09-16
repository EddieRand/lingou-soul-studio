import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import { apiAuth, ApiError, type AuthUser } from '../services/api'
import {
  AUTH_SESSION_INVALIDATED_EVENT,
  TOKEN_KEY,
  clearStoredSession,
  getStoredToken,
  saveStoredSession,
} from '../services/authSession'

export type AuthStatus = 'checking' | 'authenticated' | 'anonymous' | 'unavailable'

interface AuthContextType {
  user: AuthUser | null
  token: string | null
  authStatus: AuthStatus
  authError: string | null
  isLoggedIn: boolean
  login: (username: string, password: string) => Promise<void>
  register: (username: string, email: string, password: string) => Promise<void>
  logout: () => void
  verify: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const verificationAttemptRef = useRef(0)
  const [token, setToken] = useState<string | null>(() => getStoredToken())
  const [user, setUser] = useState<AuthUser | null>(null)
  const [authStatus, setAuthStatus] = useState<AuthStatus>(() => (
    getStoredToken() ? 'checking' : 'anonymous'
  ))
  const [authError, setAuthError] = useState<string | null>(null)

  const applyAnonymousState = useCallback(() => {
    verificationAttemptRef.current += 1
    setUser(null)
    setToken(null)
    setAuthError(null)
    setAuthStatus('anonymous')
  }, [])

  const verify = useCallback(async () => {
    const attempt = ++verificationAttemptRef.current
    const candidate = getStoredToken()
    if (!candidate) {
      applyAnonymousState()
      return
    }

    setToken(candidate)
    setAuthStatus('checking')
    setAuthError(null)
    try {
      const verifiedUser = await apiAuth.verify()
      if (attempt !== verificationAttemptRef.current || getStoredToken() !== candidate) return
      setUser(verifiedUser)
      setToken(candidate)
      setAuthStatus('authenticated')
    } catch (error) {
      if (attempt !== verificationAttemptRef.current) return
      const currentToken = getStoredToken()
      if (currentToken !== candidate) {
        if (currentToken === null) applyAnonymousState()
        return
      }
      if (error instanceof ApiError && error.status === 401) {
        clearStoredSession(candidate)
        applyAnonymousState()
        return
      }
      setUser(null)
      setToken(candidate)
      setAuthError('暂时无法验证登录状态，请检查服务后重试')
      setAuthStatus('unavailable')
    }
  }, [applyAnonymousState])

  const reconcileStoredSession = useCallback(() => {
    if (!getStoredToken()) {
      applyAnonymousState()
      return
    }
    setUser(null)
    void verify()
  }, [applyAnonymousState, verify])

  useEffect(() => {
    const handleInvalidSession = () => reconcileStoredSession()
    const handleStoredSessionChange = (event: StorageEvent) => {
      if (event.storageArea && event.storageArea !== localStorage) return
      if (event.key !== null && event.key !== TOKEN_KEY) return
      // Re-read storage because queued StorageEvent values may already be stale.
      // verify() synchronously enters checking before its first
      // await, so protected pages unmount before another account can render.
      reconcileStoredSession()
    }
    window.addEventListener(AUTH_SESSION_INVALIDATED_EVENT, handleInvalidSession)
    window.addEventListener('storage', handleStoredSessionChange)
    void verify()
    return () => {
      window.removeEventListener(AUTH_SESSION_INVALIDATED_EVENT, handleInvalidSession)
      window.removeEventListener('storage', handleStoredSessionChange)
    }
  }, [reconcileStoredSession, verify])

  async function login(username: string, password: string) {
    const result = await apiAuth.login(username, password)
    const attempt = ++verificationAttemptRef.current
    saveStoredSession(result.access_token)
    setToken(result.access_token)
    setUser(null)
    setAuthStatus('checking')
    setAuthError(null)

    try {
      const verifiedUser = await apiAuth.verify()
      if (
        attempt !== verificationAttemptRef.current
        || getStoredToken() !== result.access_token
      ) {
        throw new Error('登录状态已变化，请重试')
      }
      setUser(verifiedUser)
      setAuthStatus('authenticated')
    } catch (error) {
      if (attempt !== verificationAttemptRef.current) {
        throw new Error(
          error instanceof ApiError && error.status === 401
            ? '登录凭据未通过验证，请重新登录'
            : '登录状态已变化，请重试',
        )
      }
      const currentToken = getStoredToken()
      if (currentToken !== result.access_token) {
        if (currentToken === null) applyAnonymousState()
        throw new Error('登录状态已变化，请重试')
      }
      if (error instanceof ApiError && error.status === 401) {
        clearStoredSession(result.access_token)
        applyAnonymousState()
        throw new Error('登录凭据未通过验证，请重新登录')
      }
      setUser(null)
      setAuthStatus('unavailable')
      setAuthError('登录成功，但暂时无法向服务端确认身份')
      throw new Error('登录成功，但暂时无法向服务端确认身份')
    }
  }

  async function register(username: string, email: string, password: string) {
    await apiAuth.register(username, email, password)
  }

  function logout() {
    const currentToken = getStoredToken()
    if (currentToken) {
      void apiAuth.logout().catch(() => undefined)
      clearStoredSession(currentToken)
    } else {
      clearStoredSession()
    }
    applyAnonymousState()
  }

  return (
    <AuthContext.Provider value={{
      user,
      token,
      authStatus,
      authError,
      isLoggedIn: authStatus === 'authenticated' && user !== null,
      login,
      register,
      logout,
      verify,
      refresh: verify,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
