import { useWebSocket, CONNECTION_STATE } from '../contexts/WebSocketContext'
import { useMissionPhase, PHASE } from '../contexts/MissionPhaseContext'
import { batteryColor, formatFlightTime } from '../lib/telemetry'

function TelemetryChip({ label, value, valueStyle }) {
  return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded border border-white/10 bg-white/5">
      <span
        className="font-ui text-[11px] uppercase tracking-[0.14em]"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        {label}
      </span>
      <span
        className="font-mono text-[13px] font-medium"
        style={{ color: 'var(--color-text-primary)', ...valueStyle }}
      >
        {value}
      </span>
    </div>
  )
}

const PHASE_LABEL = {
  [PHASE.PRE_FLIGHT]: 'PRE-FLIGHT',
  [PHASE.ACTIVE]: 'ACTIVE',
  [PHASE.POST_FLIGHT]: 'POST-FLIGHT',
}

function phaseBadgeColor(phase) {
  switch (phase) {
    case PHASE.ACTIVE:
      return 'var(--color-status-normal)'
    case PHASE.POST_FLIGHT:
      return 'var(--color-text-secondary)'
    default:
      return 'var(--color-status-standby)'
  }
}

function PhaseBadge({ phase }) {
  const color = phaseBadgeColor(phase)
  const isActive = phase === PHASE.ACTIVE

  return (
    <span
      className={isActive ? 'phase-badge-active' : undefined}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 8px',
        borderRadius: '9999px',
        border: `1px solid ${color}`,
        background: `color-mix(in oklch, ${color} 12%, transparent)`,
        color,
        fontFamily: 'var(--font-mono)',
        fontSize: '10px',
        fontWeight: 400,
        letterSpacing: '0.1em',
        textTransform: 'uppercase',
      }}
    >
      {PHASE_LABEL[phase]}
    </span>
  )
}

function statusDotColor(connectionState) {
  switch (connectionState) {
    case CONNECTION_STATE.CONNECTED:
      return 'var(--color-status-normal)'
    case CONNECTION_STATE.RECONNECTING:
      return 'var(--color-status-caution)'
    default:
      return 'var(--color-status-off)'
  }
}

export default function AppHeader() {
  const { data: telemetry, connectionState } = useWebSocket('drone.telemetry')
  const { phase } = useMissionPhase()

  const bat = telemetry?.battery ?? null
  const alt = telemetry?.height_cm ?? null
  const ft = telemetry?.flight_time_s ?? null

  const batDisplay = bat !== null ? `${bat}%` : '--'
  const altDisplay = alt !== null ? `${alt}cm` : '--'
  const ftDisplay = formatFlightTime(ft)

  return (
    <header
      className="h-12 flex-shrink-0 flex items-center justify-between px-6 z-10"
      style={{
        borderBottom: '1px solid var(--color-border-default)',
        background: 'rgba(10, 10, 15, 0.95)',
        backdropFilter: 'blur(12px)',
      }}
    >
      {/* Left: logo */}
      <div className="flex items-baseline gap-4">
        <span
          className="font-ui font-semibold uppercase text-[15px]"
          style={{
            letterSpacing: '0.14em',
            color: 'var(--color-accent-blue)',
          }}
        >
          BREACHEYE
        </span>
        <span
          className="font-ui text-[11px]"
          style={{
            color: 'var(--color-text-subtle)',
            letterSpacing: '0.05em',
          }}
        >
          Autonomous Indoor Mapping · NatSec 2026
        </span>
      </div>

      {/* Center: mission phase badge */}
      <PhaseBadge phase={phase} />

      {/* Right: telemetry chips + connection dot */}
      <div className="flex items-center gap-2">
        <TelemetryChip
          label="BAT"
          value={batDisplay}
          valueStyle={{ color: batteryColor(bat) }}
        />
        <TelemetryChip label="ALT" value={altDisplay} />
        <TelemetryChip label="T" value={ftDisplay} />

        {/* Connection status dot */}
        <div
          className="w-2 h-2 rounded-full ml-2 flex-shrink-0"
          style={{ background: statusDotColor(connectionState) }}
          title={connectionState}
        />
      </div>
    </header>
  )
}
