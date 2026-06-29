// src/pages/ForgotPasswordPage.tsx
import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [token, setToken] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [step, setStep] = useState<'email' | 'token' | 'reset' | 'done'>('email')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  async function handleSubmitEmail(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!email) {
      setError('请输入邮箱')
      return
    }
    setLoading(true)
    try {
      const resp = await fetch('/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      })
      if (!resp.ok) {
        const err = await resp.json()
        throw new Error(err.detail || '获取重置链接失败')
      }
      const data = await resp.json()
      setToken(data.reset_token)
      setStep('token')
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmitReset(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!newPassword || !confirmPassword) {
      setError('请填写新密码')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的密码不一致')
      return
    }
    setLoading(true)
    try {
      const resp = await fetch('/api/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: newPassword })
      })
      if (!resp.ok) {
        const err = await resp.json()
        throw new Error(err.detail || '重置密码失败')
      }
      setStep('done')
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
            <span className="text-2xl">🔑</span>
          </div>
          <h1 className="text-2xl font-bold text-white mb-2">找回密码</h1>
          <p className="text-purple-300 text-sm">
            {step === 'email' && '输入注册时的邮箱'}
            {step === 'token' && '复制下方的重置token'}
            {step === 'reset' && '设置新密码'}
            {step === 'done' && '密码重置成功'}
          </p>
        </div>

        {step === 'email' && (
          <form onSubmit={handleSubmitEmail} className="space-y-4">
            <div>
              <label className="block text-white text-sm font-medium mb-2">邮箱</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-4 py-3 bg-white/10 border border-white/20 rounded-xl text-white placeholder-purple-300 focus:outline-none focus:border-purple-400 transition-colors"
                placeholder="请输入邮箱"
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
              {loading ? '处理中…' : '获取重置链接'}
            </button>
          </form>
        )}

        {step === 'token' && (
          <div className="space-y-4">
            <div>
              <label className="block text-white text-sm font-medium mb-2">重置 Token</label>
              <textarea
                value={token}
                readOnly
                className="w-full px-4 py-3 bg-white/10 border border-white/20 rounded-xl text-white focus:outline-none focus:border-purple-400 transition-colors resize-none"
                rows={4}
              />
              <button
                onClick={() => navigator.clipboard.writeText(token)}
                className="mt-2 w-full py-2 bg-white/10 border border-white/20 rounded-xl text-purple-300 hover:bg-white/20 transition-colors text-sm"
              >
                复制 Token
              </button>
            </div>

            <button
              onClick={() => setStep('reset')}
              className="w-full py-3 bg-gradient-to-r from-purple-500 to-pink-500 text-white font-medium rounded-xl hover:opacity-90 transition-opacity"
            >
              下一步：设置新密码
            </button>
          </div>
        )}

        {step === 'reset' && (
          <form onSubmit={handleSubmitReset} className="space-y-4">
            <div>
              <label className="block text-white text-sm font-medium mb-2">新密码</label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="w-full px-4 py-3 bg-white/10 border border-white/20 rounded-xl text-white placeholder-purple-300 focus:outline-none focus:border-purple-400 transition-colors"
                placeholder="请输入新密码（至少6位）"
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
                placeholder="请再次输入新密码"
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
              {loading ? '处理中…' : '重置密码'}
            </button>
          </form>
        )}

        {step === 'done' && (
          <div className="text-center space-y-4">
            <div className="w-16 h-16 mx-auto rounded-full bg-green-500/20 flex items-center justify-center">
              <span className="text-3xl">✓</span>
            </div>
            <p className="text-green-400">密码重置成功！</p>
            <button
              onClick={() => navigate('/login')}
              className="w-full py-3 bg-gradient-to-r from-purple-500 to-pink-500 text-white font-medium rounded-xl hover:opacity-90 transition-opacity"
            >
              返回登录
            </button>
          </div>
        )}

        <div className="mt-6 text-center">
          <p className="text-purple-300 text-sm">
            <Link to="/login" className="text-pink-400 hover:underline">
              返回登录
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
