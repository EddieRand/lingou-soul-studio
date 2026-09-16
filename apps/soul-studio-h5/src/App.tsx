import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import PageLayout from './components/PageLayout'
import { AuthProvider, useAuth } from './context/AuthContext'
import BindBasePage from './pages/BindBasePage'
import CreateSoulPage from './pages/CreateSoulPage'
import DialogueDebugPage from './pages/DialogueDebugPage'
import EditSoulPage from './pages/EditSoulPage'
import HardwareSimPage from './pages/HardwareSimPage'
import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import OnboardingPage from './pages/OnboardingPage'
import RegisterPage from './pages/RegisterPage'
import SoulDetailPage from './pages/SoulDetailPage'
import VoiceSelectPage from './pages/VoiceSelectPage'
import { getPostLoginPath } from './utils/onboarding'

const DEV_TOOLS_ENABLED = import.meta.env.DEV
  && import.meta.env.VITE_ENABLE_DEV_TOOLS === '1'

function AuthStatusScreen() {
  const { authStatus, authError, verify, logout } = useAuth()
  const unavailable = authStatus === 'unavailable'

  return (
    <main className="min-h-screen bg-gradient-to-br from-purple-950 via-indigo-950 to-purple-900 flex items-center justify-center p-6 text-center">
      <div className="glass-card w-full max-w-sm p-6">
        <div className="mx-auto mb-4 h-10 w-10 rounded-full border-2 border-white/30 border-t-white animate-spin" />
        <p className="font-bold text-white">
          {unavailable ? '暂时无法确认登录状态' : '正在恢复登录状态…'}
        </p>
        {unavailable && (
          <>
            <p className="mt-2 text-sm text-purple-200">{authError}</p>
            <div className="mt-5 flex justify-center gap-3">
              <button type="button" className="btn-soul px-6 py-2" onClick={() => void verify()}>
                重试
              </button>
              <button
                type="button"
                className="rounded-full border border-white/30 px-5 py-2 text-sm font-bold text-white"
                onClick={logout}
              >
                退出登录
              </button>
            </div>
          </>
        )}
      </div>
    </main>
  )
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { authStatus } = useAuth()
  const location = useLocation()
  if (authStatus === 'checking' || authStatus === 'unavailable') {
    return <AuthStatusScreen />
  }
  if (authStatus === 'anonymous') {
    const from = `${location.pathname}${location.search}${location.hash}`
    return <Navigate to="/login" replace state={{ from }} />
  }
  return <>{children}</>
}

function PublicOnlyRoute({ children }: { children: React.ReactNode }) {
  const { authStatus } = useAuth()
  const location = useLocation()
  if (authStatus === 'checking' || authStatus === 'unavailable') {
    return <AuthStatusScreen />
  }
  if (authStatus === 'authenticated') {
    const requestedPath = (location.state as { from?: string } | null)?.from
    const destination = requestedPath?.startsWith('/') ? requestedPath : getPostLoginPath()
    return <Navigate to={destination} replace />
  }
  return <>{children}</>
}

function RootRoute() {
  const { authStatus } = useAuth()
  if (authStatus === 'checking' || authStatus === 'unavailable') {
    return <AuthStatusScreen />
  }
  if (authStatus === 'anonymous') {
    return <Navigate to="/login" replace />
  }
  return <Navigate to={getPostLoginPath()} replace />
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<RootRoute />} />

          <Route path="/login" element={<PublicOnlyRoute><LoginPage /></PublicOnlyRoute>} />
          <Route path="/register" element={<PublicOnlyRoute><RegisterPage /></PublicOnlyRoute>} />

          <Route path="/onboarding" element={<ProtectedRoute><OnboardingPage /></ProtectedRoute>} />
          <Route path="/bind" element={<ProtectedRoute><BindBasePage /></ProtectedRoute>} />
          <Route path="/home" element={<ProtectedRoute><PageLayout><HomePage /></PageLayout></ProtectedRoute>} />
          <Route path="/conversation" element={<ProtectedRoute><PageLayout><DialogueDebugPage /></PageLayout></ProtectedRoute>} />
          <Route path="/dialogue-debug" element={<Navigate to="/conversation" replace />} />
          <Route
            path="/dev/simulate"
            element={DEV_TOOLS_ENABLED
              ? <ProtectedRoute><PageLayout><HardwareSimPage /></PageLayout></ProtectedRoute>
              : <Navigate to="/home" replace />}
          />
          <Route
            path="/dev/voices"
            element={DEV_TOOLS_ENABLED
              ? <ProtectedRoute><PageLayout><VoiceSelectPage /></PageLayout></ProtectedRoute>
              : <Navigate to="/home" replace />}
          />
          <Route path="/simulate" element={<Navigate to="/home" replace />} />
          <Route path="/voice-select" element={<Navigate to="/home" replace />} />
          <Route path="/create" element={<ProtectedRoute><CreateSoulPage /></ProtectedRoute>} />
          <Route path="/soul/:id/edit" element={<ProtectedRoute><EditSoulPage /></ProtectedRoute>} />
          <Route path="/soul/:id" element={<ProtectedRoute><PageLayout><SoulDetailPage /></PageLayout></ProtectedRoute>} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
