export interface CreateSoulDraft {
  version: 1
  name: string
  oneLine: string
  creationRequestId: string
  updatedAt: string
}

const DRAFT_PREFIX = 'lingou_create_draft_v1'

function createRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `create-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
}

export function createDraftKey(userId: string): string {
  return `${DRAFT_PREFIX}:${userId}`
}

export function emptyCreateDraft(): CreateSoulDraft {
  return {
    version: 1,
    name: '',
    oneLine: '',
    creationRequestId: createRequestId(),
    updatedAt: new Date().toISOString(),
  }
}

export function loadCreateDraft(
  userId: string,
  storage: Pick<Storage, 'getItem'> = localStorage,
): CreateSoulDraft {
  try {
    const raw = storage.getItem(createDraftKey(userId))
    if (!raw) return emptyCreateDraft()
    const parsed = JSON.parse(raw)
    if (
      parsed?.version !== 1
      || typeof parsed.name !== 'string'
      || typeof parsed.oneLine !== 'string'
      || typeof parsed.creationRequestId !== 'string'
      || !parsed.creationRequestId
    ) return emptyCreateDraft()
    return {
      version: 1,
      name: parsed.name.slice(0, 12),
      oneLine: parsed.oneLine.slice(0, 80),
      creationRequestId: parsed.creationRequestId.slice(0, 128),
      updatedAt: typeof parsed.updatedAt === 'string'
        ? parsed.updatedAt
        : new Date().toISOString(),
    }
  } catch {
    return emptyCreateDraft()
  }
}

export function saveCreateDraft(
  userId: string,
  draft: CreateSoulDraft,
  storage: Pick<Storage, 'setItem'> = localStorage,
): void {
  storage.setItem(createDraftKey(userId), JSON.stringify({
    ...draft,
    name: draft.name.slice(0, 12),
    oneLine: draft.oneLine.slice(0, 80),
    updatedAt: new Date().toISOString(),
  }))
}

export function clearCreateDraft(
  userId: string,
  storage: Pick<Storage, 'removeItem'> = localStorage,
): void {
  storage.removeItem(createDraftKey(userId))
}
