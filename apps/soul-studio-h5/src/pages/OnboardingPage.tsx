import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { isOnboardingDone, markOnboardingDone } from '../utils/onboarding'

interface OnboardingStep {
  image: string
  title: string
  primaryAction: string
}

const steps: OnboardingStep[] = [
  {
    image: '/onboarding/onboarding-step-1.png',
    title: '绑定你的灵偶底座',
    primaryAction: '下一步',
  },
  {
    image: '/onboarding/onboarding-step-2.png',
    title: '为手办创建 Soul Profile',
    primaryAction: '下一步',
  },
  {
    image: '/onboarding/onboarding-step-3.png',
    title: '叫名字，或触摸底座',
    primaryAction: '开始创建',
  },
]

export default function OnboardingPage() {
  const navigate = useNavigate()
  const [stepIndex, setStepIndex] = useState(0)
  const currentStep = steps[stepIndex]

  const stepLabel = useMemo(() => `${stepIndex + 1} / ${steps.length}`, [stepIndex])

  useEffect(() => {
    if (isOnboardingDone()) {
      navigate('/home', { replace: true })
    }
  }, [navigate])

  function complete(destination: '/home' | '/create') {
    markOnboardingDone()
    navigate(destination, { replace: true })
  }

  function handlePrimaryAction() {
    if (stepIndex < steps.length - 1) {
      setStepIndex(index => index + 1)
      return
    }
    complete('/create')
  }

  return (
    <main className="onboarding-page" aria-label="灵偶新手引导">
      <section className="onboarding-shell" aria-live="polite">
        <img
          className="onboarding-art"
          src={currentStep.image}
          alt={currentStep.title}
          draggable={false}
        />

        <button
          type="button"
          className="onboarding-hotspot onboarding-hotspot--skip"
          onClick={() => complete('/home')}
          aria-label="跳过新手引导"
        />

        <button
          type="button"
          className="onboarding-hotspot onboarding-hotspot--primary"
          onClick={handlePrimaryAction}
          aria-label={currentStep.primaryAction}
        />

        <p className="sr-only">
          新手引导第 {stepLabel} 步：{currentStep.title}
        </p>
      </section>
    </main>
  )
}
