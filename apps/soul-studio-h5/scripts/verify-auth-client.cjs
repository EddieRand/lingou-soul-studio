const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const ts = require('typescript')

const projectRoot = path.resolve(__dirname, '..')
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lingou-auth-client-'))

function compile(sourceRelativePath, outputName) {
  const source = fs.readFileSync(path.join(projectRoot, sourceRelativePath), 'utf8')
  const result = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
      esModuleInterop: true,
    },
    fileName: sourceRelativePath,
  })
  fs.writeFileSync(path.join(tempDir, outputName), result.outputText)
}

class MemoryStorage {
  constructor() {
    this.values = new Map()
  }

  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null
  }

  setItem(key, value) {
    this.values.set(key, String(value))
  }

  removeItem(key) {
    this.values.delete(key)
  }

  clear() {
    this.values.clear()
  }
}

class TestCustomEvent extends Event {
  constructor(type, init = {}) {
    super(type)
    this.detail = init.detail
  }
}

async function expectReject(promise, predicate) {
  try {
    await promise
  } catch (error) {
    assert.ok(predicate(error), `unexpected error: ${error}`)
    return
  }
  assert.fail('expected promise to reject')
}

async function main() {
  compile('src/services/authSession.ts', 'authSession.js')
  compile('src/services/api.ts', 'api.js')

  global.localStorage = new MemoryStorage()
  global.window = new EventTarget()
  global.CustomEvent = TestCustomEvent

  const session = require(path.join(tempDir, 'authSession.js'))
  const api = require(path.join(tempDir, 'api.js'))

  let captured
  global.fetch = async (url, options) => {
    captured = { url, options }
    return new Response(JSON.stringify([]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  localStorage.setItem('lingou_user_id', 'legacy-user')
  session.saveStoredSession('current-token')
  assert.equal(localStorage.getItem('lingou_user_id'), null)
  assert.equal(session.USER_ID_KEY, undefined)
  await api.apiSouls.getArchetypes()
  assert.equal(captured.options.headers.get('Authorization'), 'Bearer current-token')

  await api.request('/header-check', { headers: { 'X-Probe': 'present' } })
  assert.equal(captured.options.headers.get('Authorization'), 'Bearer current-token')
  assert.equal(captured.options.headers.get('X-Probe'), 'present')

  const form = new FormData()
  form.append('fixture', 'value')
  await api.request('/form-check', { method: 'POST', body: form })
  assert.equal(captured.options.headers.get('Authorization'), 'Bearer current-token')
  assert.equal(captured.options.headers.has('Content-Type'), false)

  let invalidationEvents = 0
  window.addEventListener(session.AUTH_SESSION_INVALIDATED_EVENT, () => {
    invalidationEvents += 1
  })
  global.fetch = async () => {
    session.saveStoredSession('newer-token')
    return new Response(JSON.stringify({ detail: 'expired' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  await expectReject(
    api.request('/late-response'),
    error => error instanceof api.ApiError && error.status === 401,
  )
  assert.equal(session.getStoredToken(), 'newer-token')
  assert.equal(invalidationEvents, 0)

  localStorage.setItem(session.LEGACY_USERNAME_KEY, 'legacy')
  localStorage.setItem('lingou_user_id', 'user-2')
  global.fetch = async () => new Response(JSON.stringify({ detail: 'expired' }), {
    status: 401,
    headers: { 'Content-Type': 'application/json' },
  })
  await expectReject(
    api.request('/current-response'),
    error => error instanceof api.ApiError && error.status === 401,
  )
  assert.equal(session.getStoredToken(), null)
  assert.equal(localStorage.getItem('lingou_user_id'), null)
  assert.equal(localStorage.getItem(session.LEGACY_USERNAME_KEY), null)
  assert.equal(invalidationEvents, 1)

  global.fetch = async () => new Response(JSON.stringify({ detail: 'missing credentials' }), {
    status: 401,
    headers: { 'Content-Type': 'application/json' },
  })
  await expectReject(
    api.request('/tokenless-current-response'),
    error => error instanceof api.ApiError && error.status === 401,
  )
  assert.equal(session.getStoredToken(), null)
  assert.equal(invalidationEvents, 2)

  global.fetch = async () => {
    session.saveStoredSession('token-after-tokenless-request')
    return new Response(JSON.stringify({ detail: 'late missing credentials' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  await expectReject(
    api.request('/late-tokenless-response'),
    error => error instanceof api.ApiError && error.status === 401,
  )
  assert.equal(session.getStoredToken(), 'token-after-tokenless-request')
  assert.equal(invalidationEvents, 2)

  session.saveStoredSession('access-token')
  global.fetch = async (url, options) => {
    captured = { url, options }
    return new Response(JSON.stringify({ ticket: 'short-ticket', expires_in: 60 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  const ticket = await api.apiAuth.createWebSocketTicket('BASE-001')
  assert.equal(ticket.ticket, 'short-ticket')
  assert.equal(captured.options.headers.get('Authorization'), 'Bearer access-token')
  assert.deepEqual(JSON.parse(captured.options.body), { base_id: 'BASE-001' })

  global.fetch = async (url, options) => {
    captured = { url, options }
    return new Response(JSON.stringify([]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  await api.apiBases.list()
  assert.equal(captured.url, '/api/bases')
  assert.equal(captured.options.headers.get('Authorization'), 'Bearer access-token')

  await api.apiBases.createTestBase('base-owner-safe')
  assert.equal(captured.url, '/api/bases/test-bases')
  assert.deepEqual(JSON.parse(captured.options.body), { base_id: 'base-owner-safe' })

  global.fetch = async (url, options) => {
    captured = { url, options }
    return new Response(JSON.stringify({
      success: true,
      base_id: 'owned-base',
      binding_status: 'bound_to_current_user',
      newly_bound: true,
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  const pairing = await api.apiBases.bind({ qr_token: 'lingou://pair?token=fixture' })
  assert.equal(pairing.base_id, 'owned-base')
  assert.equal(captured.url, '/api/bases/pair')
  assert.equal(captured.options.method, 'POST')
  assert.deepEqual(
    JSON.parse(captured.options.body),
    { qr_token: 'lingou://pair?token=fixture' },
  )

  global.fetch = async () => new Response(JSON.stringify({
    detail: 'already bound',
    error_code: 'BASE_ALREADY_BOUND',
  }), {
    status: 409,
    headers: { 'Content-Type': 'application/json' },
  })
  await expectReject(
    api.apiBases.bind({ qr_token: 'occupied' }),
    error => error instanceof api.ApiError
      && error.status === 409
      && error.code === 'BASE_ALREADY_BOUND',
  )

  global.fetch = async (url, options) => {
    captured = { url, options }
    return new Response(JSON.stringify({
      success: true,
      binding_status: 'unbound',
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  await api.apiBases.unbind({ base_id: 'BASE/unsafe path' })
  assert.equal(captured.url, '/api/bases/BASE%2Funsafe%20path/unbind')
  assert.equal(captured.options.method, 'POST')

  await api.apiSync.download('2026-09-14T12:34:56+08:00')
  const downloadUrl = new URL(captured.url, 'https://lingou.test')
  assert.equal(downloadUrl.pathname, '/api/sync/download')
  assert.equal(downloadUrl.searchParams.get('last_sync_at'), '2026-09-14T12:34:56+08:00')
  assert.equal(downloadUrl.searchParams.has('user_id'), false)
  assert.equal(captured.options.method, 'POST')

  const syncPayload = { figures: [], dialogue_logs: [], events: [] }
  await api.apiSync.upload(syncPayload)
  assert.deepEqual(JSON.parse(captured.options.body), syncPayload)
  assert.equal(api.apiSync.migrate, undefined)

  for (const status of [403, 404]) {
    global.fetch = async () => new Response(JSON.stringify({ detail: 'resource unavailable' }), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
    await expectReject(
      api.request(`/resource-${status}`),
      error => error instanceof api.ApiError && error.status === status,
    )
    assert.equal(session.getStoredToken(), 'access-token')
    assert.equal(invalidationEvents, 2)
  }

  localStorage.setItem('lingou_token', 'stale-token')
  global.fetch = async (url, options) => {
    captured = { url, options }
    return new Response(JSON.stringify({ detail: 'bad credentials' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  await expectReject(api.apiAuth.login('fixture', 'wrong-password'), error => error.status === 401)
  assert.equal(captured.options.headers.has('Authorization'), false)
  assert.equal(session.getStoredToken(), 'stale-token')
  assert.equal(invalidationEvents, 2)

  const appSource = fs.readFileSync(path.join(projectRoot, 'src/App.tsx'), 'utf8')
  const apiSource = fs.readFileSync(path.join(projectRoot, 'src/services/api.ts'), 'utf8')
  const authContextSource = fs.readFileSync(path.join(projectRoot, 'src/context/AuthContext.tsx'), 'utf8')
  const homeSource = fs.readFileSync(path.join(projectRoot, 'src/pages/HomePage.tsx'), 'utf8')
  const createSource = fs.readFileSync(path.join(projectRoot, 'src/pages/CreateSoulPage.tsx'), 'utf8')
  const hardwareSource = fs.readFileSync(path.join(projectRoot, 'src/pages/HardwareSimPage.tsx'), 'utf8')
  const bindSource = fs.readFileSync(path.join(projectRoot, 'src/pages/BindBasePage.tsx'), 'utf8')
  const loginSource = fs.readFileSync(path.join(projectRoot, 'src/pages/LoginPage.tsx'), 'utf8')
  const dialogueSource = fs.readFileSync(path.join(projectRoot, 'src/pages/DialogueDebugPage.tsx'), 'utf8')
  const voiceControllerSource = fs.readFileSync(path.join(projectRoot, 'src/services/voiceCallController.ts'), 'utf8')
  const voiceHookSource = fs.readFileSync(path.join(projectRoot, 'src/hooks/useVoiceCall.ts'), 'utf8')
  const sourceFiles = fs.readdirSync(path.join(projectRoot, 'src/pages'))
    .filter(name => name.endsWith('.tsx'))
    .map(name => fs.readFileSync(path.join(projectRoot, 'src/pages', name), 'utf8'))
    .join('\n')

  assert.equal(appSource.includes('/forgot-password'), false)
  assert.match(appSource, /path="\/bind" element={<ProtectedRoute>/)
  assert.equal(/wechat|apple-login|wechat-login/i.test(loginSource), false)
  assert.match(loginSource, /login\(username\.trim\(\), password\)/)
  assert.equal(sourceFiles.includes('ForgotPasswordPage.tsx'), false)
  assert.equal(/fetch\s*\(/.test(sourceFiles), false)
  assert.match(authContextSource, /verificationAttemptRef/)
  assert.match(authContextSource, /attempt !== verificationAttemptRef\.current/)
  assert.equal(authContextSource.includes("getStoredToken() !== candidate && getStoredToken() !== null"), false)
  assert.match(authContextSource, /addEventListener\('storage'/)
  assert.match(authContextSource, /removeEventListener\('storage'/)
  assert.match(authContextSource, /TOKEN_KEY/)
  assert.equal(authContextSource.includes('event.newValue'), false)
  assert.equal(/\bBASE-001\b/.test(sourceFiles), false)
  assert.equal(/\buser_default\b/.test(sourceFiles), false)
  assert.equal(/VALID_QR_001|ALREADY_BOUND_QR|模拟扫描正确二维码/.test(bindSource), false)
  assert.match(bindSource, /BarcodeDetector/)
  assert.match(bindSource, /apiBases\.bind\(\{\s*qr_token:/)
  assert.equal(/interface CloudSyncRequest\s*{[^}]*\buser_id\b/s.test(apiSource), false)
  assert.equal(/\bbound_user_id\b/.test(apiSource), false)
  assert.equal(/\bbindLegacy\b/.test(apiSource), false)
  assert.equal(/bind:\s*async\s*\(params:\s*\{[^}]*\bbase_id\b/s.test(apiSource), false)
  assert.equal(/\bmigrate\s*:/.test(apiSource), false)
  for (const [name, source, emptyGuard, protectedResource] of [
    ['home', homeSource, 'if (!currentBase', 'apiFigures.list()'],
    ['create', createSource, 'if (!base)', 'apiFigures.list()'],
    ['hardware', hardwareSource, 'if (!currentBase', 'apiFigures.list()'],
  ]) {
    const baseListIndex = source.indexOf('apiBases.list()')
    const emptyGuardIndex = source.indexOf(emptyGuard, baseListIndex)
    const protectedResourceIndex = source.indexOf(protectedResource, baseListIndex)
    assert.ok(baseListIndex >= 0, `${name} must load owned bases first`)
    assert.ok(emptyGuardIndex > baseListIndex, `${name} must guard an empty base list`)
    assert.ok(
      protectedResourceIndex > emptyGuardIndex,
      `${name} must not load owner resources before the empty-base guard`,
    )
  }
  assert.match(homeSource, /onClick=\{logout\}/)
  assert.match(homeSource, />\s*退出(?:登录)?\s*</)
  assert.match(voiceControllerSource, /lingou\.ticket\.\$\{ticket\}/)
  assert.equal(dialogueSource.includes('lingou_token'), false)
  assert.equal(dialogueSource.includes('access_token'), false)
  assert.equal(/getUserMedia|new WebSocket|AudioContext|reconnectTimerRef/.test(dialogueSource), false)
  assert.match(dialogueSource, /useVoiceCall\(\{ onServerMessage: handleVoiceServerMessage \}\)/)
  assert.match(dialogueSource, /message\.turnId === turnId/)
  assert.match(voiceControllerSource, /AUTH_CLOSE_CODES = new Set\(\[4401, 4403, 4409\]\)/)
  assert.match(voiceControllerSource, /event\.code === 4410/)
  assert.match(voiceControllerSource, /case 'session_replaced'/)
  assert.match(voiceControllerSource, /private scheduleReconnect\(\)/)
  assert.match(voiceControllerSource, /private releaseResources\(/)
  assert.match(voiceHookSource, /controllerRef\.current\?\.destroy\(\)/)
  assert.match(voiceHookSource, /queueMicrotask\(/)
  assert.match(voiceHookSource, /apiAuth\.createWebSocketTicket\(baseId\)/)
  assert.match(dialogueSource, /function endVoiceCall\(\)[\s\S]*stopManagedCall\('user_hangup'\)/)
  assert.equal(/async function startVoiceCall\(\)[\s\S]*setMessages\(\[\]\)/.test(dialogueSource), false)
  assert.match(createSource, /creation_request_id:\s*draft\.creationRequestId/)
  assert.match(createSource, /activate_base_id:\s*baseId/)
  assert.equal(/handleCreate\(\)[\s\S]*apiFigures\.saveCharacter/.test(createSource), false)
  assert.equal(/handleCreate\(\)[\s\S]*apiBases\.setActiveFigure/.test(createSource), false)

  console.log('frontend auth probe: PASS')
}

main()
  .finally(() => fs.rmSync(tempDir, { recursive: true, force: true }))
  .catch(error => {
    console.error(error)
    process.exitCode = 1
  })
