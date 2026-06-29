// components/PageLayout.tsx - 页面布局（内容 + 底部导航）
import BottomNav from './BottomNav'

interface PageLayoutProps {
  children: React.ReactNode
  hideNav?: boolean
  paddingBottom?: string
}

export default function PageLayout({ children, hideNav = false, paddingBottom = 'pb-52' }: PageLayoutProps) {
  return (
    <div className="min-h-[100svh] overflow-x-hidden bg-castle relative">
      <div className={`relative z-10 ${paddingBottom}`}>
        {children}
      </div>
      {!hideNav && <BottomNav />}
    </div>
  )
}
