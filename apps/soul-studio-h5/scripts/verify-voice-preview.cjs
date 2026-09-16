const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const ts = require('typescript')

const projectRoot = path.resolve(__dirname, '..')
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lingou-voice-preview-'))

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

class FakeAudio {
  preload = ''
  src = ''
  onloadeddata = null
  onplaying = null
  onended = null
  onerror = null
  pauseCount = 0
  loadCount = 0
  playResult = Promise.resolve()

  load() {
    this.loadCount += 1
  }

  play() {
    return this.playResult
  }

  pause() {
    this.pauseCount += 1
  }

  removeAttribute(name) {
    if (name === 'src') this.src = ''
  }
}

function createFixture(overrides = {}) {
  const requests = []
  const states = []
  const audios = []
  const revoked = []
  let now = 1000
  const { VoicePreviewController } = require(
    path.join(tempDir, 'voicePreviewController.js'),
  )
  const controller = new VoicePreviewController(
    {
      fetchAudio: async (request, signal) => {
        requests.push({ request, signal })
        if (overrides.fetchAudio) return overrides.fetchAudio(request, signal)
        return {
          blob: new Blob(['audio-bytes'], { type: 'audio/mpeg' }),
          engine: 'fixture-tts',
          source: 'synthesized',
          speaker: request.speaker,
          synthesizedAt: new Date(now).toISOString(),
          transferredAt: new Date(now + 1).toISOString(),
        }
      },
      createAudio: () => {
        const audio = new FakeAudio()
        if (overrides.configureAudio) overrides.configureAudio(audio)
        audios.push(audio)
        return audio
      },
      createObjectURL: () => 'blob:fixture-audio',
      revokeObjectURL: url => revoked.push(url),
      now: () => ++now,
    },
    {
      onState: state => states.push(state),
    },
  )
  return { controller, requests, states, audios, revoked }
}

async function testExactCandidateAndPlaybackPhases() {
  const fixture = createFixture()
  await fixture.controller.preview({
    speaker: 'speaker-b',
    text: 'candidate preview',
  }, 'speaker-b')
  assert.equal(fixture.requests.length, 1)
  assert.equal(fixture.requests[0].request.speaker, 'speaker-b')
  assert.equal(fixture.controller.snapshot.status, 'transferred')

  const audio = fixture.audios[0]
  audio.onloadeddata()
  assert.equal(fixture.controller.snapshot.status, 'decoded')
  audio.onplaying()
  assert.equal(fixture.controller.snapshot.status, 'playing')
  audio.onended()
  assert.equal(fixture.controller.snapshot.status, 'completed')
  assert.ok(fixture.controller.snapshot.timestamps.playbackCompleted)
  assert.deepEqual(fixture.revoked, ['blob:fixture-audio'])
}

async function testStopInvalidatesLateSynthesis() {
  const pending = deferred()
  const fixture = createFixture({
    fetchAudio: () => pending.promise,
  })
  const preview = fixture.controller.preview({
    speaker: 'speaker-late',
    text: 'late',
  })
  fixture.controller.stop()
  assert.equal(fixture.requests[0].signal.aborted, true)
  pending.resolve({
    blob: new Blob(['late']),
    engine: 'fixture',
    source: 'synthesized',
    speaker: 'speaker-late',
    synthesizedAt: '',
    transferredAt: '',
  })
  await preview
  assert.equal(fixture.audios.length, 0)
  assert.equal(fixture.controller.snapshot.status, 'idle')
}

async function testPlaybackFailureIsNotReportedAsSuccess() {
  const fixture = createFixture({
    configureAudio: audio => {
      audio.playResult = Promise.reject(new Error('autoplay denied'))
    },
  })
  await fixture.controller.preview({
    speaker: 'speaker-fail',
    text: 'failure',
  })
  assert.equal(fixture.controller.snapshot.status, 'error')
  assert.match(fixture.controller.snapshot.error, /autoplay denied/)
  assert.deepEqual(fixture.revoked, ['blob:fixture-audio'])
}

async function testEmptyAudioIsRejected() {
  const fixture = createFixture({
    fetchAudio: async request => ({
      blob: new Blob([]),
      engine: 'fixture',
      source: 'synthesized',
      speaker: request.speaker,
      synthesizedAt: '',
      transferredAt: '',
    }),
  })
  await fixture.controller.preview({
    speaker: 'speaker-empty',
    text: 'empty',
  })
  assert.equal(fixture.controller.snapshot.status, 'error')
  assert.match(fixture.controller.snapshot.error, /没有收到/)
  assert.equal(fixture.audios.length, 0)
}

async function main() {
  compile('src/services/voicePreviewController.ts', 'voicePreviewController.js')
  await testExactCandidateAndPlaybackPhases()
  await testStopInvalidatesLateSynthesis()
  await testPlaybackFailureIsNotReportedAsSuccess()
  await testEmptyAudioIsRejected()
  console.log('frontend voice preview probe: 4/4 PASS')
}

main()
  .finally(() => fs.rmSync(tempDir, { recursive: true, force: true }))
  .catch(error => {
    console.error(error)
    process.exitCode = 1
  })
