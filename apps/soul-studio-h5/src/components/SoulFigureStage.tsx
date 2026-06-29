import type { CSSProperties } from 'react'

type SoulFigureLike = {
  figure_id?: string
  name?: string
  avatar_url?: string | null
}

const FIGURE_PALETTES = [
  ['#7c3aed', '#ec4899', '#f8a4d8'],
  ['#4f46e5', '#06b6d4', '#bae6fd'],
  ['#f97316', '#ef4444', '#fed7aa'],
  ['#059669', '#14b8a6', '#bbf7d0'],
  ['#9333ea', '#6366f1', '#ddd6fe'],
]

function paletteStyle(seed = '') {
  const code = seed.split('').reduce((sum, char) => sum + char.charCodeAt(0), 0)
  const palette = FIGURE_PALETTES[code % FIGURE_PALETTES.length]
  return {
    '--figure-a': palette[0],
    '--figure-b': palette[1],
    '--figure-c': palette[2],
  } as CSSProperties
}

export default function SoulFigureStage({
  figure,
  moodFilter = '',
  className = '',
}: {
  figure?: SoulFigureLike | null
  moodFilter?: string
  className?: string
}) {
  const name = figure?.name || '灵偶'
  const avatarUrl = figure?.avatar_url || ''

  return (
    <div className={`profile-figure-art ${className}`} style={paletteStyle(figure?.figure_id || name)}>
      {avatarUrl ? (
        <img className="profile-figure-art__image" src={avatarUrl} alt={name} style={{ filter: moodFilter }} />
      ) : (
        <div className="profile-figure-art__fallback" style={{ filter: moodFilter }} aria-hidden="true">
          <span className="profile-figure-art__portrait">
            <span className="profile-figure-art__hair" />
            <span className="profile-figure-art__head" />
            <span className="profile-figure-art__neck" />
            <span className="profile-figure-art__body" />
            <span className="profile-figure-art__collar" />
          </span>
          <span className="profile-figure-art__name">{name.slice(0, 1)}</span>
        </div>
      )}
    </div>
  )
}
