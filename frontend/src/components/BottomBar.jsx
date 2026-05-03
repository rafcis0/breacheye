import { useState } from 'react'
import { useWebSocket, CONNECTION_STATE } from '../contexts/WebSocketContext'

function Separator() {
  return <span className="h-4 border-l border-white/10 mx-2" />
}

function StatusItem({ label, value, valueStyle }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className="font-ui text-[11px] uppercase tracking-[0.14em]"
        style={{ color: 'var(--color-text-subtle)' }}
      >
        {label}
      </span>
      <span
        className="font-mono text-[11px] font-medium"
        style={{ color: 'var(--color-text-secondary)', ...valueStyle }}
      >
        {value}
      </span>
    </div>
  )
}

function wsHealthLabel(connectionState) {
  switch (connectionState) {
    case CONNECTION_STATE.CONNECTED:
      return { text: 'LIVE', color: 'var(--color-status-normal)' }
    case CONNECTION_STATE.RECONNECTING:
      return { text: 'RECONNECTING', color: 'var(--color-status-caution)' }
    default:
      return { text: 'OFFLINE', color: 'var(--color-status-off)' }
  }
}

export default function BottomBar() {
  const { data: telemetry, connectionState } = useWebSocket('drone.telemetry')
  const { data: detectionsData } = useWebSocket('drone.detections')
  const [view3D, setView3D] = useState(false)

  const connected = telemetry?.connected ?? false
  const flying = telemetry?.flying ?? false
  const mode = flying ? 'AIRBORNE' : 'GROUNDED'
  const modeColor = flying ? 'var(--color-accent-blue)' : 'var(--color-text-subtle)'

  const linkColor = connected
    ? 'var(--color-status-normal)'
    : 'var(--color-status-off)'

  const poiCount = Array.isArray(detectionsData?.detections)
    ? detectionsData.detections.length
    : 0

  const wsHealth = wsHealthLabel(connectionState)

  return (
    <footer
      className="h-8 flex-shrink-0 flex items-center justify-between px-4 z-10"
      style={{
        borderTop: '1px solid var(--color-border-default)',
        background: 'var(--color-bg-deeper)',
        backdropFilter: 'blur(12px)',
      }}
    >
      {/* Left: system indicators */}
      <div className="flex items-center">
        <StatusItem
          label="LINK"
          value={connected ? 'UP' : 'DOWN'}
          valueStyle={{ color: linkColor }}
        />
        <Separator />
        <StatusItem
          label="MODE"
          value={mode}
          valueStyle={{ color: modeColor }}
        />
        <Separator />
        <StatusItem
          label="POI"
          value={String(poiCount)}
        />
        <Separator />
        {/* WS health */}
        <div className="flex items-center gap-1.5">
          <span
            className="w-1.5 h-1.5 rounded-full flex-shrink-0"
            style={{ background: wsHealth.color }}
          />
          <span
            className="font-mono text-[11px] font-medium"
            style={{ color: wsHealth.color }}
          >
            {wsHealth.text}
          </span>
        </div>
      </div>

      {/* Right: 3D toggle placeholder */}
      <button
        type="button"
        onClick={() => setView3D((v) => !v)}
        className="flex items-center gap-1.5 px-2 py-0.5 rounded border transition-colors"
        style={{
          borderColor: view3D
            ? 'var(--color-accent-blue)'
            : 'var(--color-border-default)',
          background: view3D ? 'rgba(86, 124, 219, 0.15)' : 'transparent',
          color: view3D
            ? 'var(--color-accent-blue)'
            : 'var(--color-text-secondary)',
        }}
      >
        <span className="font-mono text-[11px] font-medium">[3D]</span>
      </button>
    </footer>
  )
}
