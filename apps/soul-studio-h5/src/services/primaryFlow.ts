import type { BaseDetail, FigureProfile } from './api'

export type PrimaryFlowDecision =
  | { action: 'bind' }
  | { action: 'create'; base: BaseDetail }
  | { action: 'activate'; base: BaseDetail; figure: FigureProfile }
  | { action: 'ready'; base: BaseDetail; figure: FigureProfile }

export function resolvePrimaryFlow(
  bases: BaseDetail[],
  figures: FigureProfile[],
): PrimaryFlowDecision {
  const base = bases[0]
  if (!base) return { action: 'bind' }
  if (base.figure) return { action: 'ready', base, figure: base.figure }

  const activeFigure = base.base.active_figure_id
    ? figures.find(figure => figure.figure_id === base.base.active_figure_id)
    : null
  if (activeFigure) return { action: 'ready', base, figure: activeFigure }
  if (figures[0]) return { action: 'activate', base, figure: figures[0] }
  return { action: 'create', base }
}

export function conversationPath(figureId: string): string {
  return `/conversation?figure_id=${encodeURIComponent(figureId)}`
}
