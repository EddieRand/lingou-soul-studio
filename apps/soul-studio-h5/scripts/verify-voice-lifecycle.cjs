const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const ts = require('typescript')

const projectRoot = path.resolve(__dirname, '..')
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lingou-voice-lifecycle-'))

function compile(sourceRelativePath, outputName) {
  const source = fs.readFileSync(path.join(projectRoot, sourceRelativePath), 'utf8')
  const result = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
    },
    fileName: sourceRelativePath,
  })
  fs.writeFileSync(path.join(tempDir, outputName), result.outputText)
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function flush() {
  return new Promise(resolve => setImmediate(resolve))
}

class FakeTrack {
  stopped = 0
  stop() {
    this.stopped += 1
  }
}

class FakeStream {
  constructor() {
    this.track = new FakeTrack()
  }
  getTracks() {
    return [this.track]
  }
}

class FakeNode {
  disconnected = 0
  connect() {}
  disconnect() {
    this.disconnected += 1
  }
}

class FakeProcessor extends FakeNode {
  onaudioprocess = null
}

class FakeBufferSource extends FakeNode {
  buffer = null
  onended = null
  started = 0
  stopped = 0
  start() {
    this.started += 1
  }
  stop() {
    this.stopped += 1
  }
}

class FakeAudioContext {
  constructor() {
    this.sampleRate = 48000
    this.currentTime = 0
    this.state = 'running'
    this.destination = {}
    this.sources = []
    this.closeCount = 0
    this.decodeDeferred = null
  }
  createMediaStreamSource() {
    this.mediaSource = new FakeNode()
    return this.mediaSource
  }
  createScriptProcessor() {
    this.processor = new FakeProcessor()
    return this.processor
  }
  createGain() {
    this.gainNode = new FakeNode()
    this.gainNode.gain = { value: 1 }
    return this.gainNode
  }
  createBufferSource() {
    const source = new FakeBufferSource()
    this.sources.push(source)
    return source
  }
  decodeAudioData() {
    if (this.decodeDeferred) return this.decodeDeferred.promise
    return Promise.resolve({ duration: 0.25 })
  }
  close() {
    this.closeCount += 1
    this.state = 'closed'
    return Promise.resolve()
  }
}

class FakeWebSocket {
  constructor() {
    this.readyState = 0
    this.binaryType = ''
    this.sent = []
    this.closeCount = 0
    this.onopen = null
    this.onmessage = null
    this.onerror = null
    this.onclose = null
  }
  open() {
    this.readyState = 1
    this.onopen?.({})
  }
  message(data) {
    this.onmessage?.({ data })
  }
  unexpectedClose(code = 1006) {
    this.readyState = 3
    this.onclose?.({ code })
  }
  send(payload) {
    this.sent.push(payload)
  }
  close() {
    this.closeCount += 1
    this.readyState = 3
  }
}

function createFixture(overrides = {}) {
  const states = []
  const messages = []
  const streams = []
  const contexts = []
  const sockets = []
  const timers = new Map()
  let nextTimer = 1
  let mediaCalls = 0
  let ticketCalls = 0

  const dependencies = {
    getUserMedia: async () => {
      mediaCalls += 1
      if (overrides.getUserMedia) return overrides.getUserMedia(mediaCalls)
      const stream = new FakeStream()
      streams.push(stream)
      return stream
    },
    createAudioContext: () => {
      const context = new FakeAudioContext()
      contexts.push(context)
      return context
    },
    createWebSocket: () => {
      const socket = new FakeWebSocket()
      sockets.push(socket)
      return socket
    },
    createTicket: async baseId => {
      ticketCalls += 1
      return { ticket: `ticket-${baseId}-${ticketCalls}` }
    },
    websocketUrl: baseId => `ws://test/api/asr/stream?base_id=${baseId}`,
    setTimer: callback => {
      const id = nextTimer++
      timers.set(id, callback)
      return id
    },
    clearTimer: id => timers.delete(id),
    reconnectDelayMs: 1,
    maxReconnectAttempts: 3,
  }
  const { VoiceCallController } = require(path.join(tempDir, 'voiceCallController.js'))
  const controller = new VoiceCallController(dependencies, {
    onState: state => states.push(state),
    onServerMessage: message => messages.push(message),
  })
  return {
    controller,
    states,
    messages,
    streams,
    contexts,
    sockets,
    timers,
    get mediaCalls() { return mediaCalls },
    get ticketCalls() { return ticketCalls },
  }
}

async function testDoubleStartCreatesOneSession() {
  const fixture = createFixture()
  await Promise.all([
    fixture.controller.start('BASE-1'),
    fixture.controller.start('BASE-1'),
  ])
  assert.equal(fixture.mediaCalls, 1)
  assert.equal(fixture.ticketCalls, 1)
  assert.equal(fixture.sockets.length, 1)
  fixture.sockets[0].open()
  assert.equal(fixture.controller.snapshot.status, 'listening')
  await fixture.controller.start('BASE-1')
  assert.equal(fixture.sockets.length, 1)
  fixture.controller.destroy()
}

async function testStopWhilePermissionPendingReleasesLateStream() {
  const pending = deferred()
  const fixture = createFixture({
    getUserMedia: () => pending.promise,
  })
  const start = fixture.controller.start('BASE-PENDING')
  fixture.controller.stop()
  const stream = new FakeStream()
  pending.resolve(stream)
  await start
  assert.equal(stream.track.stopped, 1)
  assert.equal(fixture.ticketCalls, 0)
  assert.equal(fixture.sockets.length, 0)
  assert.equal(fixture.controller.snapshot.status, 'idle')
}

async function testPermissionDenialCanBeRetried() {
  const fixture = createFixture({
    getUserMedia: call => {
      if (call === 1) {
        const error = new Error('denied')
        error.name = 'NotAllowedError'
        return Promise.reject(error)
      }
      const stream = new FakeStream()
      fixture.streams.push(stream)
      return stream
    },
  })
  await fixture.controller.start('BASE-PERMISSION')
  assert.equal(fixture.controller.snapshot.status, 'permission_denied')
  assert.equal(fixture.controller.snapshot.active, false)
  await fixture.controller.start('BASE-PERMISSION')
  assert.equal(fixture.sockets.length, 1)
  fixture.sockets[0].open()
  assert.equal(fixture.controller.snapshot.status, 'listening')
  fixture.controller.destroy()
}

async function testReconnectKeepsHistoryAndCreatesOneReplacement() {
  const fixture = createFixture()
  const visibleHistory = []
  await fixture.controller.start('BASE-RECONNECT')
  const first = fixture.sockets[0]
  first.open()
  first.message(JSON.stringify({
    type: 'final',
    session_id: 'session-one',
    turn_id: 'turn-one',
    text: 'hello',
  }))
  visibleHistory.push(...fixture.messages)
  first.unexpectedClose()
  assert.equal(fixture.controller.snapshot.status, 'reconnecting')
  assert.equal(fixture.timers.size, 1)

  const reconnect = [...fixture.timers.values()][0]
  fixture.timers.clear()
  reconnect()
  await flush()
  await flush()
  assert.equal(fixture.sockets.length, 2)
  fixture.sockets[1].open()
  assert.equal(fixture.controller.snapshot.status, 'listening')
  assert.equal(visibleHistory.length, 1)
  await fixture.controller.start('BASE-RECONNECT')
  assert.equal(fixture.sockets.length, 2)
  fixture.controller.destroy()
}

async function testTerminalReplacementNeverReconnects() {
  const fixture = createFixture()
  await fixture.controller.start('BASE-REPLACED')
  const socket = fixture.sockets[0]
  socket.open()
  socket.unexpectedClose(4410)
  assert.equal(fixture.controller.snapshot.status, 'replaced')
  assert.equal(fixture.controller.snapshot.active, false)
  assert.equal(fixture.timers.size, 0)
}

async function testHangupCancelsPendingReconnect() {
  const fixture = createFixture()
  await fixture.controller.start('BASE-HANGUP')
  const socket = fixture.sockets[0]
  socket.open()
  socket.unexpectedClose()
  const reconnect = [...fixture.timers.values()][0]
  fixture.controller.stop()
  reconnect()
  await flush()
  assert.equal(fixture.sockets.length, 1)
  assert.equal(fixture.controller.snapshot.status, 'idle')
}

async function testDestroyReleasesEveryOwnedResource() {
  const fixture = createFixture()
  await fixture.controller.start('BASE-DESTROY')
  const stream = fixture.streams[0]
  const context = fixture.contexts[0]
  const socket = fixture.sockets[0]
  socket.open()
  fixture.controller.destroy()
  assert.equal(stream.track.stopped, 1)
  assert.equal(context.closeCount, 1)
  assert.equal(context.processor.disconnected, 1)
  assert.equal(context.mediaSource.disconnected, 1)
  assert.equal(context.gainNode.disconnected, 1)
  assert.equal(socket.closeCount, 1)
  assert.equal(fixture.controller.snapshot.status, 'idle')
}

async function testLateAudioDecodeCannotSchedulePlayback() {
  const fixture = createFixture()
  await fixture.controller.start('BASE-AUDIO')
  const context = fixture.contexts[0]
  const socket = fixture.sockets[0]
  context.decodeDeferred = deferred()
  socket.open()
  socket.message(JSON.stringify({
    type: 'audio_output',
    stage: 'synthesized',
    session_id: 'session-late',
    turn_id: 'turn-late',
    audio_id: 'turn-late:1',
  }))
  socket.message(new ArrayBuffer(8))
  fixture.controller.stop()
  context.decodeDeferred.resolve({ duration: 1 })
  await flush()
  assert.equal(context.sources.length, 0)
}

async function testStopAudioInvalidatesDecodeAlreadyInProgress() {
  const fixture = createFixture()
  await fixture.controller.start('BASE-BARGE-IN-AUDIO')
  const context = fixture.contexts[0]
  const socket = fixture.sockets[0]
  context.decodeDeferred = deferred()
  socket.open()
  socket.message(JSON.stringify({
    type: 'audio_output',
    stage: 'synthesized',
    session_id: 'session-barge-in',
    turn_id: 'turn-barge-in',
    audio_id: 'turn-barge-in:1',
  }))
  socket.message(new ArrayBuffer(8))
  socket.message(JSON.stringify({
    type: 'stop_audio',
    session_id: 'session-barge-in',
    turn_id: 'turn-barge-in',
  }))
  context.decodeDeferred.resolve({ duration: 1 })
  await flush()
  await flush()

  const receipts = socket.sent
    .filter(item => typeof item === 'string')
    .map(item => JSON.parse(item))
    .filter(item => item.type === 'audio_playback')
  assert.equal(context.sources.length, 0)
  assert.deepEqual(receipts, [])
  assert.equal(fixture.controller.snapshot.status, 'listening')
  fixture.controller.destroy()
}

async function testAudioPlaybackReportsEveryClientStage() {
  const fixture = createFixture()
  await fixture.controller.start('BASE-AUDIO-STAGES')
  const socket = fixture.sockets[0]
  const context = fixture.contexts[0]
  socket.open()
  socket.message(JSON.stringify({
    type: 'speaking',
    status: 'start',
    session_id: 'session-audio',
    turn_id: 'turn-audio',
  }))
  socket.message(JSON.stringify({
    type: 'audio_output',
    stage: 'synthesized',
    session_id: 'session-audio',
    turn_id: 'turn-audio',
    audio_id: 'turn-audio:1',
    content_type: 'audio/mpeg',
    byte_length: 8,
  }))
  socket.message(new ArrayBuffer(8))
  socket.message(JSON.stringify({
    type: 'audio_output',
    stage: 'transferred',
    session_id: 'session-audio',
    turn_id: 'turn-audio',
    audio_id: 'turn-audio:1',
  }))
  await flush()
  await flush()

  assert.equal(context.sources.length, 1)
  assert.equal(context.sources[0].started, 1)
  let receipts = socket.sent
    .filter(item => typeof item === 'string')
    .map(item => JSON.parse(item))
    .filter(item => item.type === 'audio_playback')
  assert.deepEqual(
    receipts.map(item => item.stage),
    ['decoded', 'playback_started'],
  )
  assert.ok(receipts.every(item => item.turn_id === 'turn-audio'))
  assert.ok(receipts.every(item => item.audio_id === 'turn-audio:1'))

  context.sources[0].onended()
  socket.message(JSON.stringify({
    type: 'speaking',
    status: 'end',
    session_id: 'session-audio',
    turn_id: 'turn-audio',
  }))
  receipts = socket.sent
    .filter(item => typeof item === 'string')
    .map(item => JSON.parse(item))
    .filter(item => item.type === 'audio_playback')
  assert.deepEqual(
    receipts.map(item => item.stage),
    ['decoded', 'playback_started', 'playback_completed'],
  )
  assert.equal(fixture.controller.snapshot.audioStatus, 'completed')
  assert.equal(fixture.controller.snapshot.status, 'listening')
  fixture.controller.destroy()
}

async function testAudioDecodeFailureIsVisibleAndReported() {
  const fixture = createFixture()
  await fixture.controller.start('BASE-AUDIO-FAIL')
  const socket = fixture.sockets[0]
  const context = fixture.contexts[0]
  context.decodeAudioData = () => Promise.reject(new Error('bad audio'))
  socket.open()
  socket.message(JSON.stringify({
    type: 'audio_output',
    stage: 'synthesized',
    session_id: 'session-fail',
    turn_id: 'turn-fail',
    audio_id: 'turn-fail:1',
  }))
  socket.message(new ArrayBuffer(8))
  await flush()
  await flush()

  const receipts = socket.sent
    .filter(item => typeof item === 'string')
    .map(item => JSON.parse(item))
    .filter(item => item.type === 'audio_playback')
  assert.equal(receipts.at(-1).stage, 'playback_failed')
  assert.equal(fixture.controller.snapshot.audioStatus, 'failed')
  assert.match(fixture.controller.snapshot.error, /解码失败/)
  fixture.controller.destroy()
}

async function main() {
  compile('src/services/voiceCallController.ts', 'voiceCallController.js')
  await testDoubleStartCreatesOneSession()
  await testStopWhilePermissionPendingReleasesLateStream()
  await testPermissionDenialCanBeRetried()
  await testReconnectKeepsHistoryAndCreatesOneReplacement()
  await testTerminalReplacementNeverReconnects()
  await testHangupCancelsPendingReconnect()
  await testDestroyReleasesEveryOwnedResource()
  await testLateAudioDecodeCannotSchedulePlayback()
  await testStopAudioInvalidatesDecodeAlreadyInProgress()
  await testAudioPlaybackReportsEveryClientStage()
  await testAudioDecodeFailureIsVisibleAndReported()
  console.log('frontend voice lifecycle probe: 11/11 PASS')
}

main()
  .finally(() => fs.rmSync(tempDir, { recursive: true, force: true }))
  .catch(error => {
    console.error(error)
    process.exitCode = 1
  })
