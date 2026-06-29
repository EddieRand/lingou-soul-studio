// src/context/AuthContext.tsx
import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'

interface User {
  user_id: string
  username: string
  email: string
  created_at: string
}

interface AuthContextType {
  user: User | null
  token: string | null
  isLoggedIn: boolean
  login: (username: string, password: string) => Promise<void>
  register: (username: string, email: string, password: string) => Promise<void>
  logout: () => void
  verify: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)

  useEffect(() => {
    const savedToken = localStorage.getItem('lingou_token')
    if (savedToken) {
      setToken(savedToken)
      verify()
    }
  }, [])

  async function verify() {
    // 从 localStorage 读取最新的 token
    const currentToken = localStorage.getItem('lingou_token')
    if (!currentToken) return
    try {
      const resp = await fetch('/api/auth/verify', {
        headers: { Authorization: `Bearer ${currentToken}` }
      })
      const data = await resp.json()
      if (data.user_id) {
        setToken(currentToken)
        setUser(data)
      }
    } catch {
      logout()
    }
  }

  async function refresh() {
    // 强制刷新用户状态
    await verify()
  }

  async function login(username: string, password: string) {
    const resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username, password })
    })
    if (!resp.ok) {
      const err = await resp.json()
      throw new Error(err.detail || '登录失败')
    }
    const data = await resp.json()
    setToken(data.access_token)
    setUser({
      user_id: data.user_id,
      username: data.username,
      email: '',
      created_at: ''
    })
    localStorage.setItem('lingou_token', data.access_token)
    localStorage.setItem('lingou_user_id', data.user_id)

    try {
      await fetch('/api/sync/migrate', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${data.access_token}`
        },
        body: JSON.stringify({ user_id: data.user_id })
      })
    } catch {
      console.log('Data migration skipped')
    }
  }

  async function register(username: string, email: string, password: string) {
    const resp = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password })
    })
    if (!resp.ok) {
      const err = await resp.json()
      throw new Error(err.detail || '注册失败')
    }
  }

  function logout() {
    setUser(null)
    setToken(null)
    localStorage.removeItem('lingou_token')
    localStorage.removeItem('lingou_user_id')
  }

  return (
    <AuthContext.Provider value={{
      user,
      token,
      isLoggedIn: !!user,
      login,
      register,
      logout,
      verify,
      refresh
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
