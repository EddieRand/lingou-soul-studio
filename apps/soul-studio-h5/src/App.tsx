import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import HomePage from './pages/HomePage'
import BindBasePage from './pages/BindBasePage'
import HardwareSimPage from './pages/HardwareSimPage'
import DialogueDebugPage from './pages/DialogueDebugPage'
import VoiceSelectPage from './pages/VoiceSelectPage'
import CreateSoulPage from './pages/CreateSoulPage'
import SoulDetailPage from './pages/SoulDetailPage'
import EditSoulPage from './pages/EditSoulPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import OnboardingPage from './pages/OnboardingPage'
import PageLayout from './components/PageLayout'
import { AuthProvider, useAuth } from './context/AuthContext'
import { getPostLoginPath } from './utils/onboarding'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isLoggedIn } = useAuth()
  if (!isLoggedIn) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

function RootRoute() {
  const { isLoggedIn } = useAuth()
  if (!isLoggedIn) {
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

          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />

          <Route path="/onboarding" element={
            <ProtectedRoute>
              <OnboardingPage />
            </ProtectedRoute>
          } />

          <Route path="/bind" element={<BindBasePage />} />

          <Route path="/home" element={
            <ProtectedRoute>
              <PageLayout><HomePage /></PageLayout>
            </ProtectedRoute>
          } />
          <Route path="/simulate" element={
            <ProtectedRoute>
              <PageLayout><HardwareSimPage /></PageLayout>
            </ProtectedRoute>
          } />
          <Route path="/dialogue-debug" element={
            <ProtectedRoute>
              <PageLayout><DialogueDebugPage /></PageLayout>
            </ProtectedRoute>
          } />
          <Route path="/voice-select" element={
            <ProtectedRoute>
              <PageLayout><VoiceSelectPage /></PageLayout>
            </ProtectedRoute>
          } />

          <Route path="/create" element={
            <ProtectedRoute>
              <CreateSoulPage />
            </ProtectedRoute>
          } />
          <Route path="/soul/:id/edit" element={
            <ProtectedRoute>
              <EditSoulPage />
            </ProtectedRoute>
          } />

          <Route path="/soul/:id" element={
            <ProtectedRoute>
              <PageLayout><SoulDetailPage /></PageLayout>
            </ProtectedRoute>
          } />

          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
