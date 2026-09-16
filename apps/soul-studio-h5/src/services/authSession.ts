export const TOKEN_KEY = 'lingou_token'
export const LEGACY_USERNAME_KEY = 'lingou_username'
export const AUTH_SESSION_INVALIDATED_EVENT = 'lingou:session-invalidated'

const LEGACY_USER_ID_KEY = 'lingou_user_id'

export interface SessionInvalidatedDetail {
  token: string | null
}

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function saveStoredSession(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.removeItem(LEGACY_USER_ID_KEY)
  localStorage.removeItem(LEGACY_USERNAME_KEY)
}

export function clearStoredSession(expectedToken?: string | null): boolean {
  const currentToken = getStoredToken()
  if (expectedToken !== undefined && currentToken !== expectedToken) {
    return false
  }
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(LEGACY_USER_ID_KEY)
  localStorage.removeItem(LEGACY_USERNAME_KEY)
  return true
}

export function invalidateStoredSession(requestToken: string | null): boolean {
  // A late 401 from an old request must never erase a newer login.
  if (!clearStoredSession(requestToken)) {
    return false
  }
  window.dispatchEvent(new CustomEvent<SessionInvalidatedDetail>(
    AUTH_SESSION_INVALIDATED_EVENT,
    { detail: { token: requestToken } },
  ))
  return true
}
