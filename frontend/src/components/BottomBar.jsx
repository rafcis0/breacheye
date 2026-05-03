import { useWebSocket, CONNECTION_STATE } from '../contexts/WebSocketContext'

function Separator() {
  return (
    <span
      className="mx-3 flex-shrink-0"
      style={{
        width: '1px',
        height: '16px',
        background: 'rgba(255,255,255,0.10)',
        display: 'inline-block',
      }}
    />
  )
}

function StatusItem({ label, value, valueStyle }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className="font-ui text-[11px] uppercase tracking-[0.12em]"
        style={{ color: 'var(--color-text-subtle)' }}
      >
        {label}
      </span>
      <span
        className="font-mono text-[11px]"
        style={{ color: 'var(--color-text-secondary)', ...valueStyle }}
      >
        {value}
      </span>
    </div>
  )
}

function StatusDotItem({ label, dotColor, text, textColor }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className="font-ui text-[11px] uppercase tracking-[0.12em]"
        style={{ color: 'var(--color-text-subtle)' }}
      >
        {label}
      </span>
      <span
        className="inline-block rounded-full flex-shrink-0"
        style={{ width: '7px', height: '7px', background: dotColor }}
      />
      <span
        className="font-mono text-[11px]"
        style={{ color: textColor }}
      >
        {text}
      </span>
    </div>
  )
}

function linkStatus(connected, connectionState) {
  if (connectionState === CONNECTION_STATE.RECONNECTING) {
    return { text: 'RECONNECTING', color: 'var(--color-status-caution)' }
  }
  if (connected) {
    return { text: 'CONNECTED', color: 'var(--color-status-normal)' }
  }
  return { text: 'DOWN', color: 'var(--color-status-critical)' }
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

  const connected = telemetry?.connected ?? false
  const flying = telemetry?.flying ?? false
  const mode = flying ? 'AIRBORNE' : 'GROUNDED'
  const modeColor = flying ? 'var(--color-accent-blue)' : 'var(--color-text-subtle)'

  const link = linkStatus(connected, connectionState)
  const poiCount = Array.isArray(detectionsData?.detections)
    ? detectionsData.detections.length
    : 0

  const wsHealth = wsHealthLabel(connectionState)

  return (
    <footer
      className="h-8 flex-shrink-0 flex items-center justify-between px-4 z-10"
      style={{
        borderTop: '1px solid var(--color-border-default)',
        background: 'rgba(10,10,15,0.95)',
        backdropFilter: 'blur(12px)',
      }}
    >
      {/* Left: system indicators */}
      <div className="flex items-center">
        <StatusDotItem
          label="LINK"
          dotColor={link.color}
          text={link.text}
          textColor={link.color}
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
        {/* WS health with dot */}
        <StatusDotItem
          label="WS"
          dotColor={wsHealth.color}
          text={wsHealth.text}
          textColor={wsHealth.color}
        />
      </div>

      {/* Right: 3D toggle placeholder */}
      <button
        type="button"
        disabled
        className="flex items-center gap-1.5 px-2 py-0.5 rounded border opacity-40 cursor-not-allowed"
        title="3D view coming soon"
        style={{
          borderColor: 'var(--color-border-default)',
          background: 'transparent',
          color: 'var(--color-text-secondary)',
        }}
      >
        <span className="font-mono text-[11px] font-medium">[3D]</span>
      </button>
    </footer>
  )
}
