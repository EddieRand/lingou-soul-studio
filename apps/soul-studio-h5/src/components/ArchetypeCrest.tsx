// components/ArchetypeCrest.tsx - 气质纹章占位（CSS 渐变菱形 + 星纹）
interface ArchetypeCrestProps {
  archetype?: string
  size?: number
  className?: string
}

const ARCHETYPE_COLORS: Record<string, [string, string]> = {
  '御姐照顾型': ['#8B5CF6', '#EC4899'],
  '傲娇吐槽型': ['#EC4899', '#F472B6'],
  '软萌治愈型': ['#F472B6', '#FBBF24'],
  '元气伙伴型': ['#FBBF24', '#F472B6'],
  '冷淡守护型': ['#60A5FA', '#A78BFA'],
  '桀骜战神型': ['#F97316', '#DC2626'],
  '搞怪捣蛋型': ['#A78BFA', '#F472B6'],
  '憨憨吃货型': ['#FBBF24', '#F97316'],
  '机械副官型': ['#06B6D4', '#3B82F6'],
  '萌宠陪伴型': ['#F472B6', '#A78BFA'],
  '潮玩幸运型': ['#A78BFA', '#FBBF24'],
}

export default function ArchetypeCrest({ archetype = '', size = 56, className = '' }: ArchetypeCrestProps) {
  const colors = ARCHETYPE_COLORS[archetype] || ['#8B5CF6', '#EC4899']
  return (
    <div
      className={`relative flex items-center justify-center ${className}`}
      style={{ width: size, height: size }}
    >
      {/* 渐变菱形 */}
      <div
        className="absolute inset-0 glow-soft"
        style={{
          background: `linear-gradient(135deg, ${colors[0]} 0%, ${colors[1]} 100%)`,
          clipPath: 'polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)',
          opacity: 0.85,
        }}
      />
      {/* 内层纹章 */}
      <div
        className="absolute inset-2 flex items-center justify-center"
        style={{
          background: `linear-gradient(135deg, ${colors[1]} 0%, ${colors[0]} 100%)`,
          clipPath: 'polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)',
        }}
      >
        <span
          className="text-white font-bold"
          style={{ fontSize: size * 0.32, textShadow: '0 0 4px rgba(255,255,255,0.6)' }}
        >
          ✦
        </span>
      </div>
      {/* 装饰星点 */}
      <span
        className="absolute -top-1 -right-1 text-yellow-300 twinkle"
        style={{ fontSize: size * 0.22 }}
      >
        ✧
      </span>
    </div>
  )
}
