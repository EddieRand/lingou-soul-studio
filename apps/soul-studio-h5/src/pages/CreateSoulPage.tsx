import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import StarField from '../components/StarField'
import { useAuth } from '../context/AuthContext'
import { apiBases, apiFigures, apiSouls } from '../services/api'
import {
  clearCreateDraft,
  loadCreateDraft,
  saveCreateDraft,
  type CreateSoulDraft,
} from '../services/createDraft'
import { conversationPath } from '../services/primaryFlow'
import { markOnboardingDone } from '../utils/onboarding'

const FIGURE_BASE_SRC = '/lingou_figure_soul_base_clean.png'

export default function CreateSoulPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [draft, setDraft] = useState<CreateSoulDraft | null>(null)
  const [baseId, setBaseId] = useState<string | null>(null)
  const [archetype, setArchetype] = useState('软萌治愈型')
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [restored, setRestored] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!user) return
    const saved = loadCreateDraft(user.user_id)
    setDraft(saved)
    setRestored(Boolean(saved.name || saved.oneLine))
  }, [user])

  useEffect(() => {
    if (!user || !draft) return
    saveCreateDraft(user.user_id, draft)
  }, [draft, user])

  useEffect(() => {
    let cancelled = false

    async function loadFlow() {
      try {
        const bases = await apiBases.list()
        if (cancelled) return
        const base = bases[0]
        if (!base) {
          navigate('/bind', { replace: true })
          return
        }
        if (base.figure) {
          navigate('/home', { replace: true })
          return
        }
        const figures = await apiFigures.list()
        if (cancelled) return
        if (figures[0]) {
          await apiBases.setActiveFigure(base.base.base_id, figures[0].figure_id)
          if (!cancelled) navigate('/home', { replace: true })
          return
        }
        const archetypes = await apiSouls.getArchetypes()
        if (cancelled) return
        setBaseId(base.base.base_id)
        if (archetypes[0]?.archetype) setArchetype(archetypes[0].archetype)
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : '初始化失败，请重试')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void loadFlow()
    return () => {
      cancelled = true
    }
  }, [navigate])

  async function handleCreate() {
    if (!user || !draft || !baseId || creating) return
    const name = draft.name.trim()
    const oneLine = draft.oneLine.trim()
    if (!name) {
      setError('请给灵偶起一个名字')
      return
    }
    if (!oneLine) {
      setError('请用一句话描述这个灵偶')
      return
    }

    setCreating(true)
    setError('')
    try {
      const figure = await apiFigures.create({
        creation_request_id: draft.creationRequestId,
        activate_base_id: baseId,
        name,
        figure_type: 'soul',
        wake_names: [name.slice(0, 8)],
        soul_profile: {
          archetype,
          name,
          one_line: oneLine,
          address_user_as: '你',
        },
      })
      if (figure.base_id !== baseId) {
        throw new Error('灵偶已保存，但底座激活状态异常，请重试')
      }
      clearCreateDraft(user.user_id)
      markOnboardingDone()
      navigate(conversationPath(figure.figure_id), { replace: true })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '创建失败，请重试')
    } finally {
      setCreating(false)
    }
  }

  if (loading || !draft) {
    return (
      <main className="flex min-h-[100svh] items-center justify-center bg-castle">
        <p className="text-sm font-semibold text-purple-500">正在准备当前灵偶…</p>
      </main>
    )
  }

  return (
    <main className="relative min-h-[100svh] overflow-hidden bg-castle">
      <StarField count={14} />
      <div className="relative z-10 mx-auto flex min-h-[100svh] max-w-lg flex-col px-5 pb-10 pt-8">
        <header className="flex items-center justify-between">
          <div>
            <p className="text-[10px] font-bold tracking-[0.2em] text-purple-400">CREATE SOUL</p>
            <h1 className="mt-1 text-2xl font-black text-purple-950">创建当前灵偶</h1>
          </div>
          <button
            type="button"
            onClick={() => navigate('/bind')}
            className="rounded-full bg-white/70 px-3 py-2 text-xs font-bold text-purple-600 ring-1 ring-white/80"
          >
            设备设置
          </button>
        </header>

        <section className="mt-6 grid grid-cols-[112px_1fr] items-center gap-4 rounded-[28px] bg-[#251744] p-4 text-white shadow-[0_20px_60px_rgba(76,44,135,0.2)]">
          <img
            src={FIGURE_BASE_SRC}
            alt="灵偶"
            className="aspect-[4/5] w-full rounded-[20px] object-cover"
          />
          <div>
            <p className="text-[10px] font-bold tracking-[0.18em] text-purple-200">当前底座</p>
            <p className="mt-1 truncate text-sm font-bold text-white/90">{baseId}</p>
            <p className="mt-3 text-sm leading-5 text-white/70">
              保存后直接开始第一次交流。
            </p>
          </div>
        </section>

        <section className="glass-card mt-5 space-y-5 p-5">
          {restored && (
            <p className="rounded-xl bg-emerald-50 px-3 py-2 text-xs font-bold text-emerald-700">
              已恢复上次未完成的草稿
            </p>
          )}

          <label className="block">
            <span className="text-sm font-black text-purple-950">名字</span>
            <input
              value={draft.name}
              maxLength={12}
              autoFocus
              onChange={event => {
                setRestored(false)
                setDraft(current => current && {
                  ...current,
                  name: event.target.value.slice(0, 12),
                })
              }}
              placeholder="例如：阿澈"
              className="mt-2 w-full rounded-2xl border border-purple-100 bg-white/70 px-4 py-3 text-base text-purple-950 outline-none focus:ring-2 focus:ring-purple-300"
            />
          </label>

          <label className="block">
            <span className="text-sm font-black text-purple-950">一句话设定</span>
            <textarea
              value={draft.oneLine}
              maxLength={80}
              rows={4}
              onChange={event => {
                setRestored(false)
                setDraft(current => current && {
                  ...current,
                  oneLine: event.target.value.slice(0, 80),
                })
              }}
              placeholder="例如：守护旧书店、说话冷静但很可靠"
              className="mt-2 w-full resize-none rounded-2xl border border-purple-100 bg-white/70 px-4 py-3 text-sm leading-6 text-purple-950 outline-none focus:ring-2 focus:ring-purple-300"
            />
            <span className="mt-1 block text-right text-[11px] font-semibold text-purple-300">
              {draft.oneLine.length}/80
            </span>
          </label>

          {error && (
            <p role="alert" className="rounded-2xl bg-red-50 px-3 py-2 text-sm font-semibold text-red-600">
              {error}
            </p>
          )}

          <button
            type="button"
            onClick={handleCreate}
            disabled={creating || !draft.name.trim() || !draft.oneLine.trim()}
            className="w-full rounded-2xl bg-gradient-to-r from-purple-600 to-pink-500 py-3.5 text-sm font-black text-white shadow-lg shadow-purple-200/60 disabled:opacity-40"
          >
            {creating ? '正在创建…' : '创建并开始交流'}
          </button>
        </section>
      </div>
    </main>
  )
}
