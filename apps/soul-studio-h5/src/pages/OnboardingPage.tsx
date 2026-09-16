import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiBases } from '../services/api'
import { isOnboardingDone, markOnboardingDone } from '../utils/onboarding'

export default function OnboardingPage() {
  const navigate = useNavigate()

  useEffect(() => {
    let cancelled = false
    if (isOnboardingDone()) {
      navigate('/home', { replace: true })
      return
    }
    apiBases.list()
      .then(bases => {
        if (cancelled || bases.length === 0) return
        markOnboardingDone()
        navigate('/home', { replace: true })
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [navigate])

  function startSetup() {
    markOnboardingDone()
    navigate('/bind', { replace: true })
  }

  return (
    <main className="onboarding-page" aria-label="灵偶新手引导">
      <section className="onboarding-shell">
        <img
          className="onboarding-art"
          src="/onboarding/onboarding-step-1.png"
          alt="灵偶和底座"
          draggable={false}
        />
        <div className="absolute inset-x-5 bottom-8 rounded-[28px] bg-white/90 p-5 text-center shadow-xl backdrop-blur-xl">
          <p className="text-[10px] font-bold tracking-[0.18em] text-purple-400">LINGOU</p>
          <h1 className="mt-2 text-2xl font-black text-purple-950">连接你的灵偶</h1>
          <p className="mt-2 text-sm leading-6 text-purple-500">
            绑定底座，创建一个当前角色，然后直接开始交流。
          </p>
          <button
            type="button"
            onClick={startSetup}
            className="mt-5 w-full rounded-2xl bg-gradient-to-r from-purple-600 to-pink-500 py-3.5 text-sm font-black text-white"
          >
            开始设置
          </button>
        </div>
      </section>
    </main>
  )
}
