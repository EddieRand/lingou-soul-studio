const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const ts = require('typescript')

const projectRoot = path.resolve(__dirname, '..')
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lingou-primary-flow-'))

function compile(sourceRelativePath, outputName) {
  const source = fs.readFileSync(path.join(projectRoot, sourceRelativePath), 'utf8')
  const result = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2020,
      module: ts.ModuleKind.CommonJS,
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
}

function source(relativePath) {
  return fs.readFileSync(path.join(projectRoot, relativePath), 'utf8')
}

function fixtureBase(figure = null) {
  return {
    base: {
      base_id: 'BASE-FLOW',
      active_figure_id: figure?.figure_id || null,
      status: 'bound',
    },
    figure,
  }
}

async function main() {
  compile('src/services/createDraft.ts', 'createDraft.js')
  compile('src/services/primaryFlow.ts', 'primaryFlow.js')
  const drafts = require(path.join(tempDir, 'createDraft.js'))
  const flow = require(path.join(tempDir, 'primaryFlow.js'))

  assert.deepEqual(flow.resolvePrimaryFlow([], []), { action: 'bind' })
  assert.equal(flow.resolvePrimaryFlow([fixtureBase()], []).action, 'create')

  const legacyFigure = { figure_id: 'FIGURE-OLD', name: '旧角色' }
  const activate = flow.resolvePrimaryFlow([fixtureBase()], [legacyFigure])
  assert.equal(activate.action, 'activate')
  assert.equal(activate.figure.figure_id, 'FIGURE-OLD')

  const currentFigure = { figure_id: 'FIGURE-CURRENT', name: '当前角色' }
  const ready = flow.resolvePrimaryFlow(
    [fixtureBase(currentFigure)],
    [legacyFigure, currentFigure],
  )
  assert.equal(ready.action, 'ready')
  assert.equal(ready.figure.figure_id, 'FIGURE-CURRENT')
  assert.equal(flow.conversationPath('FIGURE A'), '/conversation?figure_id=FIGURE%20A')

  const storage = new MemoryStorage()
  const initial = drafts.emptyCreateDraft()
  initial.name = '阿澈'
  initial.oneLine = '守护旧书店的灵偶'
  drafts.saveCreateDraft('OWNER-A', initial, storage)
  const restored = drafts.loadCreateDraft('OWNER-A', storage)
  assert.equal(restored.name, '阿澈')
  assert.equal(restored.oneLine, '守护旧书店的灵偶')
  assert.equal(restored.creationRequestId, initial.creationRequestId)
  assert.equal(drafts.loadCreateDraft('OWNER-B', storage).name, '')

  storage.setItem(drafts.createDraftKey('OWNER-C'), '{broken')
  assert.equal(drafts.loadCreateDraft('OWNER-C', storage).name, '')
  drafts.clearCreateDraft('OWNER-A', storage)
  assert.equal(storage.getItem(drafts.createDraftKey('OWNER-A')), null)

  const app = source('src/App.tsx')
  const nav = source('src/components/BottomNav.tsx')
  const home = source('src/pages/HomePage.tsx')
  const create = source('src/pages/CreateSoulPage.tsx')
  const conversation = source('src/pages/DialogueDebugPage.tsx')
  const detail = source('src/pages/SoulDetailPage.tsx')
  const edit = source('src/pages/EditSoulPage.tsx')

  assert.ok(app.includes('path="/conversation"'))
  assert.match(app, /VITE_ENABLE_DEV_TOOLS/)
  assert.equal(nav.includes('/simulate'), false)
  assert.doesNotMatch(nav, /互动控制台/)
  assert.doesNotMatch(home, /灵偶列表|出战|模拟触摸|创建新灵偶/)
  assert.match(home, /继续交流/)
  assert.doesNotMatch(create, /apiCharacter|CHAT_STAGES|上传图片|灵魂契约/)
  assert.match(create, /saveCreateDraft|creationRequestId|创建并开始交流/)
  assert.doesNotMatch(conversation, /apiBrain|setActiveFigure|调试设置|灵偶列表/)
  assert.doesNotMatch(detail, /simulateAbsence|boostRelationship|羁绊等级|高级工具/)
  assert.doesNotMatch(edit, /cloneStart|声音复刻|触摸反应/)

  console.log('primary user flow probe: 8/8 PASS')
}

main()
  .finally(() => fs.rmSync(tempDir, { recursive: true, force: true }))
  .catch(error => {
    console.error(error)
    process.exitCode = 1
  })
