export const ONBOARDING_DONE_KEY = 'lingou_onboarding_done'

export function isOnboardingDone() {
  return localStorage.getItem(ONBOARDING_DONE_KEY) === 'true'
}

export function markOnboardingDone() {
  localStorage.setItem(ONBOARDING_DONE_KEY, 'true')
}

export function getPostLoginPath() {
  return isOnboardingDone() ? '/home' : '/onboarding'
}
