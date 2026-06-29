// components/CharacterAvatar.tsx - 角色头像占位（渐变圆 + 缩写 / emoji）
interface CharacterAvatarProps {
  name?: string
  archetype?: string
  size?: number
  glow?: boolean
  className?: string
}

const ARCHETYPE_EMOJI: Record<string, string> = {
  '御姐照顾型': '💃',
  '傲娇吐槽型': '😤',
  '软萌治愈型': '🌸',
  '元气伙伴型': '⚡',
  '冷淡守护型': '❄️',
  '桀骜战神型': '🐵',
  '搞怪捣蛋型': '🦊',
  '憨憨吃货型': '🍖',
  '机械副官型': '🤖',
  '萌宠陪伴型': '🐱',
  '潮玩幸运型': '🎰',
}

const ARCHETYPE_GRADIENT: Record<string, string> = {
  '御姐照顾型': 'from-purple-400 via-pink-400 to-purple-500',
  '傲娇吐槽型': 'from-pink-400 via-pink-300 to-purple-300',
  '软萌治愈型': 'from-pink-200 via-pink-300 to-yellow-200',
  '元气伙伴型': 'from-yellow-300 via-orange-300 to-pink-300',
  '冷淡守护型': 'from-blue-300 via-blue-200 to-purple-300',
  '桀骜战神型': 'from-orange-400 via-red-400 to-purple-500',
  '搞怪捣蛋型': 'from-purple-300 via-pink-300 to-purple-400',
  '憨憨吃货型': 'from-yellow-300 via-orange-300 to-yellow-400',
  '机械副官型': 'from-cyan-400 via-blue-400 to-indigo-400',
  '萌宠陪伴型': 'from-pink-300 via-purple-300 to-pink-400',
  '潮玩幸运型': 'from-purple-400 via-yellow-300 to-purple-500',
}

export default function CharacterAvatar({
  archetype = '',
  size = 64,
  glow = true,
  className = '',
}: CharacterAvatarProps) {
  const gradient = ARCHETYPE_GRADIENT[archetype] || 'from-purple-400 via-pink-400 to-purple-500'
  const emoji = ARCHETYPE_EMOJI[archetype] || '✨'

  return (
    <div
      className={`relative flex items-center justify-center bg-gradient-to-br ${gradient} ${
        glow ? 'glow-soft' : ''
      } ${className}`}
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        boxShadow: glow
          ? '0 0 24px rgba(167, 139, 250, 0.5), inset 0 2px 0 rgba(255,255,255,0.4)'
          : 'inset 0 2px 0 rgba(255,255,255,0.4)',
        border: '2px solid rgba(255, 255, 255, 0.5)',
      }}
    >
      <span
        className="text-white drop-shadow-md"
        style={{ fontSize: size * 0.5 }}
      >
        {emoji}
      </span>
      {/* 装饰星点 */}
      {glow && (
        <span
          className="absolute -top-0.5 -right-0.5 text-yellow-300 twinkle"
          style={{ fontSize: size * 0.22 }}
        >
          ✦
        </span>
      )}
    </div>
  )
}
