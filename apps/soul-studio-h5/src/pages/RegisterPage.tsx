// src/pages/RegisterPage.tsx
import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function RegisterPage() {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const { register } = useAuth()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    if (!username || !email || !password) {
      setError('请填写所有字段')
      return
    }

    if (password !== confirmPassword) {
      setError('两次输入的密码不一致')
      return
    }

    if (password.length < 8) {
      setError('密码至少需要8位')
      return
    }

    if (new TextEncoder().encode(password).length > 72) {
      setError('密码的 UTF-8 编码不能超过72字节')
      return
    }

    setLoading(true)
    try {
      await register(username, email, password)
      navigate('/login')
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-900 via-indigo-900 to-purple-900 flex items-center justify-center p-4">
      <div className="glass-card w-full max-w-sm p-6">
        <div className="text-center mb-6">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
            <span className="text-2xl">✦</span>
          </div>
          <h1 className="text-2xl font-bold text-white mb-2">灵偶</h1>
          <p className="text-purple-300 text-sm">创建你的灵魂羁绊</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-white text-sm font-medium mb-2">用户名</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 py-3 bg-white/10 border border-white/20 rounded-xl text-white placeholder-purple-300 focus:outline-none focus:border-purple-400 transition-colors"
              placeholder="请输入用户名"
              autoComplete="username"
              disabled={loading}
            />
          </div>

          <div>
            <label className="block text-white text-sm font-medium mb-2">邮箱</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 py-3 bg-white/10 border border-white/20 rounded-xl text-white placeholder-purple-300 focus:outline-none focus:border-purple-400 transition-colors"
              placeholder="请输入邮箱"
              autoComplete="email"
              disabled={loading}
            />
          </div>

          <div>
            <label className="block text-white text-sm font-medium mb-2">密码</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-3 bg-white/10 border border-white/20 rounded-xl text-white placeholder-purple-300 focus:outline-none focus:border-purple-400 transition-colors"
              placeholder="请输入密码（至少8位）"
              autoComplete="new-password"
              minLength={8}
              disabled={loading}
            />
          </div>

          <div>
            <label className="block text-white text-sm font-medium mb-2">确认密码</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full px-4 py-3 bg-white/10 border border-white/20 rounded-xl text-white placeholder-purple-300 focus:outline-none focus:border-purple-400 transition-colors"
              placeholder="请再次输入密码"
              autoComplete="new-password"
              minLength={8}
              disabled={loading}
            />
          </div>

          {error && (
            <p className="text-red-400 text-sm text-center">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-gradient-to-r from-purple-500 to-pink-500 text-white font-medium rounded-xl hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {loading ? '注册中…' : '注册'}
          </button>
        </form>

        <div className="mt-6 text-center">
          <p className="text-purple-300 text-sm">
            已有账号？{' '}
            <Link to="/login" className="text-pink-400 hover:underline">
              立即登录
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
