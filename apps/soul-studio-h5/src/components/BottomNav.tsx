import { useLocation, useNavigate } from 'react-router-dom'

import LiquidGlassPanel from './LiquidGlassPanel'

const TABS = [
  { path: '/home', label: '当前灵偶', icon: '⌂' },
  { path: '/conversation', label: '继续交流', icon: '◌' },
]

export default function BottomNav() {
  const navigate = useNavigate()
  const location = useLocation()

  if (
    ['/bind', '/create', '/onboarding', '/login', '/register']
      .some(path => location.pathname.startsWith(path))
  ) return null

  return (
    <div className="bottom-nav-shell fixed left-0 right-0 z-30 px-4 pt-6">
      <LiquidGlassPanel
        className="mx-auto max-w-lg"
        contentClassName="relative flex p-1.5"
        radius={28}
        variant="nav"
      >
        {TABS.map(tab => {
          const active = location.pathname === tab.path
            || (tab.path === '/home' && location.pathname.startsWith('/soul/'))
          return (
            <button
              type="button"
              key={tab.path}
              onClick={() => navigate(tab.path)}
              className={`relative flex flex-1 flex-col items-center gap-1 rounded-[22px] py-2.5 transition-colors ${
                active
                  ? 'bg-white/70 text-purple-950 shadow-sm'
                  : 'text-purple-500 hover:text-purple-800'
              }`}
            >
              <span className="text-xl" aria-hidden="true">{tab.icon}</span>
              <span className="text-[11px] font-bold">{tab.label}</span>
            </button>
          )
        })}
      </LiquidGlassPanel>
    </div>
  )
}
