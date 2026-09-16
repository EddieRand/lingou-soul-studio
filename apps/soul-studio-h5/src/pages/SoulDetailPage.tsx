import { useEffect, useState, type CSSProperties } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import PageHeader from '../components/PageHeader'
import StarField from '../components/StarField'
import {
  apiDialogue,
  apiFigures,
  apiMemories,
  type FigureProfile,
  type MemoryCollection,
} from '../services/api'
import { conversationPath } from '../services/primaryFlow'

interface DialogueLog {
  turn_id?: string
  user_input_text: string
  reply_text: string
  created_at: string
}

const FIGURE_PALETTES = [
  ['#7c3aed', '#ec4899', '#f8a4d8'],
  ['#5b5ff5', '#a855f7', '#d8c4ff'],
  ['#db2777', '#fb7185', '#ffd1e7'],
  ['#4338ca', '#06b6d4', '#c4f1ff'],
]

function paletteStyle(seed: string): CSSProperties {
  const code = seed.split('').reduce((sum, char) => sum + char.charCodeAt(0), 0)
  const palette = FIGURE_PALETTES[code % FIGURE_PALETTES.length]
  return {
    '--figure-a': palette[0],
    '--figure-b': palette[1],
    '--figure-c': palette[2],
  } as CSSProperties
}

function FigureStage({ figure }: { figure: FigureProfile }) {
  return (
    <div className="profile-figure-art" style={paletteStyle(figure.figure_id)}>
      {figure.avatar_url ? (
        <img className="profile-figure-art__image" src={figure.avatar_url} alt={figure.name} />
      ) : (
        <div className="profile-figure-art__fallback" aria-hidden="true">
          <span className="profile-figure-art__portrait">
            <span className="profile-figure-art__hair" />
            <span className="profile-figure-art__head" />
            <span className="profile-figure-art__neck" />
            <span className="profile-figure-art__body" />
            <span className="profile-figure-art__collar" />
          </span>
          <span className="profile-figure-art__name">{figure.name.slice(0, 1)}</span>
        </div>
      )}
    </div>
  )
}

export default function SoulDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [figure, setFigure] = useState<FigureProfile | null>(null)
  const [memories, setMemories] = useState<MemoryCollection | null>(null)
  const [dialogueLogs, setDialogueLogs] = useState<DialogueLog[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [memoryDraft, setMemoryDraft] = useState('')
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null)
  const [editingMemoryContent, setEditingMemoryContent] = useState('')
  const [confirmDeleteMemoryId, setConfirmDeleteMemoryId] = useState<string | null>(null)
  const [memoryBusy, setMemoryBusy] = useState(false)
  const [memoryError, setMemoryError] = useState('')

  useEffect(() => {
    if (!id) return
    let cancelled = false

    async function loadData() {
      setLoading(true)
      try {
        const [nextFigure, nextMemories, logs] = await Promise.all([
          apiFigures.get(id!),
          apiMemories.list(id!),
          apiDialogue.getLogs(id!, 6).catch(() => []),
        ])
        if (cancelled) return
        setFigure(nextFigure)
        setMemories(nextMemories)
        setDialogueLogs(
          [...logs].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))),
        )
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : '加载失败')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void loadData()
    return () => {
      cancelled = true
    }
  }, [id])

  async function refreshMemories() {
    if (!id) return
    setMemories(await apiMemories.list(id))
  }

  async function runMemoryAction(action: () => Promise<unknown>) {
    setMemoryBusy(true)
    setMemoryError('')
    try {
      await action()
      await refreshMemories()
      return true
    } catch (reason) {
      setMemoryError(reason instanceof Error ? reason.message : '记忆操作失败')
      return false
    } finally {
      setMemoryBusy(false)
    }
  }

  async function handleCreateMemory() {
    const content = memoryDraft.trim()
    if (!id || !content) return
    if (await runMemoryAction(() => apiMemories.create(id, content))) {
      setMemoryDraft('')
    }
  }

  async function handleConfirmMemory(memoryId: string) {
    if (id) await runMemoryAction(() => apiMemories.confirm(id, memoryId))
  }

  async function handleUpdateMemory(memoryId: string) {
    const content = editingMemoryContent.trim()
    if (!id || !content) return
    if (await runMemoryAction(() => apiMemories.update(id, memoryId, content))) {
      setEditingMemoryId(null)
      setEditingMemoryContent('')
    }
  }

  async function handleDeleteMemory(memoryId: string) {
    if (!id) return
    if (await runMemoryAction(() => apiMemories.delete(id, memoryId))) {
      setConfirmDeleteMemoryId(null)
      setEditingMemoryId(null)
      setEditingMemoryContent('')
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-[100svh] items-center justify-center bg-castle">
        <p className="text-sm font-semibold text-purple-500">正在读取档案…</p>
      </main>
    )
  }

  if (error || !figure) {
    return (
      <main className="flex min-h-[100svh] flex-col items-center justify-center gap-4 bg-castle px-6 text-center">
        <p role="alert" className="text-sm font-semibold text-red-600">{error || '灵偶不存在'}</p>
        <button type="button" onClick={() => navigate('/home')} className="text-sm font-bold text-purple-600">
          返回主页
        </button>
      </main>
    )
  }

  const confirmedFacts = memories?.confirmed_facts || []
  const candidates = memories?.candidates || []
  const oneLine = figure.soul_profile?.one_line
    || figure.soul_profile?.character_profile?.one_line
    || '随时可以继续上次的话题'

  return (
    <main className="relative min-h-[100svh] overflow-hidden bg-castle">
      <StarField count={12} />
      <PageHeader
        title="当前灵偶"
        subtitle={figure.name}
        onBack={() => navigate('/home')}
        extra={
          <button
            type="button"
            onClick={() => navigate(`/soul/${figure.figure_id}/edit`)}
            className="rounded-full bg-white/70 px-3 py-1.5 text-xs font-bold text-purple-600 ring-1 ring-white/80"
          >
            编辑档案
          </button>
        }
      />

      <div className="relative z-10 mx-auto max-w-lg space-y-4 px-4 pb-32">
        <section className="profile-hero-card" style={paletteStyle(figure.figure_id)}>
          <div className="relative z-10">
            <p className="text-[10px] font-bold tracking-[0.2em] text-white/70">
              {figure.soul_profile?.archetype || '陪伴型'}
            </p>
            <h1 className="mt-1 text-3xl font-black text-white">{figure.name}</h1>
            <p className="mt-2 line-clamp-2 text-sm leading-6 text-white/80">{oneLine}</p>
          </div>
          <div className="relative z-10 mt-4 min-h-[250px] overflow-hidden rounded-[26px] bg-black/15 ring-1 ring-white/20">
            <FigureStage figure={figure} />
          </div>
          <button
            type="button"
            onClick={() => navigate(conversationPath(figure.figure_id))}
            className="relative z-10 mt-4 w-full rounded-2xl bg-white py-3 text-sm font-black text-purple-950"
          >
            继续交流
          </button>
        </section>

        <section className="glass-card p-4">
          <div className="mb-3 flex items-end justify-between gap-3">
            <div>
              <h2 className="text-base font-black text-purple-950">共同记忆</h2>
              <p className="mt-0.5 text-[11px] font-semibold text-purple-400">
                {confirmedFacts.length}/{memories?.confirmed_limit || 10} 条已确认
              </p>
            </div>
          </div>

          <div className="flex gap-2">
            <input
              value={memoryDraft}
              onChange={event => setMemoryDraft(event.target.value.slice(0, 120))}
              onKeyDown={event => {
                if (event.key === 'Enter') void handleCreateMemory()
              }}
              placeholder="添加一条需要记住的事实"
              className="min-w-0 flex-1 rounded-2xl border border-purple-100 bg-white/70 px-3 py-2.5 text-sm text-purple-900 outline-none focus:ring-2 focus:ring-purple-300"
            />
            <button
              type="button"
              onClick={handleCreateMemory}
              disabled={memoryBusy || !memoryDraft.trim() || confirmedFacts.length >= (memories?.confirmed_limit || 10)}
              className="rounded-2xl bg-purple-600 px-4 text-sm font-bold text-white disabled:opacity-40"
            >
              添加
            </button>
          </div>

          {memoryError && (
            <p role="alert" className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-xs font-semibold text-red-600">
              {memoryError}
            </p>
          )}

          {candidates.length > 0 && (
            <div className="mt-4 space-y-2">
              <p className="text-xs font-black text-amber-700">待确认</p>
              {candidates.map(memory => (
                <div key={memory.memory_id} className="memory-snippet">
                  <span className="memory-snippet__icon">候</span>
                  <p className="min-w-0 flex-1 text-sm text-purple-900">{memory.content}</p>
                  <button type="button" disabled={memoryBusy} onClick={() => handleConfirmMemory(memory.memory_id)} className="text-xs font-bold text-emerald-600">
                    确认
                  </button>
                  <button type="button" disabled={memoryBusy} onClick={() => setConfirmDeleteMemoryId(memory.memory_id)} className="text-xs font-bold text-red-500">
                    删除
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="mt-4 space-y-2">
            {confirmedFacts.length === 0 ? (
              <p className="rounded-2xl bg-white/50 py-5 text-center text-sm text-purple-400">
                暂无已确认记忆
              </p>
            ) : confirmedFacts.map(memory => (
              <div key={memory.memory_id} className="memory-snippet">
                <span className="memory-snippet__icon">记</span>
                <div className="min-w-0 flex-1">
                  {editingMemoryId === memory.memory_id ? (
                    <input
                      autoFocus
                      value={editingMemoryContent}
                      onChange={event => setEditingMemoryContent(event.target.value.slice(0, 120))}
                      className="w-full rounded-xl border border-purple-200 bg-white px-3 py-2 text-sm text-purple-900 outline-none"
                    />
                  ) : (
                    <p className="text-sm leading-5 text-purple-900">{memory.content}</p>
                  )}
                </div>
                {editingMemoryId === memory.memory_id ? (
                  <>
                    <button type="button" disabled={memoryBusy || !editingMemoryContent.trim()} onClick={() => handleUpdateMemory(memory.memory_id)} className="text-xs font-bold text-emerald-600">
                      保存
                    </button>
                    <button type="button" onClick={() => setEditingMemoryId(null)} className="text-xs font-bold text-purple-400">
                      取消
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      disabled={memoryBusy}
                      onClick={() => {
                        setEditingMemoryId(memory.memory_id)
                        setEditingMemoryContent(memory.content)
                        setConfirmDeleteMemoryId(null)
                      }}
                      className="text-xs font-bold text-purple-600"
                    >
                      修改
                    </button>
                    <button type="button" disabled={memoryBusy} onClick={() => setConfirmDeleteMemoryId(memory.memory_id)} className="text-xs font-bold text-red-500">
                      删除
                    </button>
                  </>
                )}
              </div>
            ))}
          </div>

          {confirmDeleteMemoryId && (
            <div className="mt-3 flex items-center justify-between gap-3 rounded-2xl bg-red-50 px-3 py-2">
              <p className="text-xs font-semibold text-red-600">确认删除这条记忆？</p>
              <div className="flex gap-3">
                <button type="button" onClick={() => setConfirmDeleteMemoryId(null)} className="text-xs font-bold text-purple-500">取消</button>
                <button type="button" disabled={memoryBusy} onClick={() => handleDeleteMemory(confirmDeleteMemoryId)} className="text-xs font-bold text-red-600">确认删除</button>
              </div>
            </div>
          )}
        </section>

        <section className="glass-card p-4">
          <h2 className="text-base font-black text-purple-950">最近对话</h2>
          {dialogueLogs.length === 0 ? (
            <p className="mt-3 rounded-2xl bg-white/50 py-5 text-center text-sm text-purple-400">
              还没有对话记录
            </p>
          ) : (
            <div className="mt-3 space-y-3">
              {dialogueLogs.slice(0, 3).map((log, index) => (
                <div key={log.turn_id || index} className="space-y-2">
                  <p className="ml-auto max-w-[84%] rounded-2xl bg-purple-600 px-3 py-2 text-sm text-white">
                    {log.user_input_text}
                  </p>
                  <p className="max-w-[88%] rounded-2xl bg-white/70 px-3 py-2 text-sm text-purple-900 ring-1 ring-white/80">
                    {log.reply_text}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  )
}
