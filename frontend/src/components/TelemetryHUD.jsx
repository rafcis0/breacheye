import { useEffect, useRef, useState } from 'react'
import { useWebSocket, CONNECTION_STATE } from '../contexts/WebSocketContext'

const HEALTH_URL = '/api/health'
const POLL_INTERVAL_MS = 2000

function batteryColor(battery) {
  if (battery === null || battery === undefined) return '#6b7280'
  if (battery > 50) return '#22c55e'
  if (battery >= 20) return '#eab308'
  return '#ef4444'
}

export function formatFlightTime(seconds) {
  if (seconds === null || seconds === undefined) return '--:--'
  const m = Math.floor(seconds / 60).toString().padStart(2, '0')
  const s = (seconds % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}

export default function TelemetryHUD() {
  const { data: wsData, connectionState } = useWebSocket('drone.telemetry')
  const [polledTelemetry, setPolledTelemetry] = useState(null)
  const pollRef = useRef(null)

  // Fall back to polling when WS is not connected
  useEffect(() => {
    if (connectionState === CONNECTION_STATE.CONNECTED) {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
      return
    }

    if (pollRef.current) return

    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(HEALTH_URL)
        if (res.ok) {
          const data = await res.json()
          if (data.telemetry) setPolledTelemetry(data.telemetry)
        }
      } catch {
        // server not yet up, keep trying
      }
    }, POLL_INTERVAL_MS)

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [connectionState])

  // Prefer live WS data; fall back to polled
  const telemetry = wsData ?? polledTelemetry

  const wsConnected = connectionState === CONNECTION_STATE.CONNECTED

  const bat = telemetry?.battery ?? null
  const alt = telemetry?.height_cm ?? null
  const ft = telemetry?.flight_time_s ?? null
  const connected = telemetry?.connected ?? false
  const flying = telemetry?.flying ?? false

  return (
    <div className="telemetry-hud">
      <div className="telemetry-hud__header">
        <span className="telemetry-hud__title">TELEMETRY HUD</span>
        <span className="telemetry-hud__ws" style={{ color: wsConnected ? '#22c55e' : '#6b7280' }}>
          {wsConnected ? 'LIVE' : 'DELAYED'}
        </span>
      </div>

      <div className="telemetry-hud__rows">
        <div className="telemetry-hud__row">
          <span className="telemetry-hud__label">BATTERY</span>
          <span className="telemetry-hud__value" style={{ color: batteryColor(bat) }}>
            {bat !== null ? `${bat}%` : '--'}
          </span>
        </div>

        <div className="telemetry-hud__row">
          <span className="telemetry-hud__label">ALTITUDE</span>
          <span className="telemetry-hud__value">
            {alt !== null ? `${alt} cm` : '--'}
          </span>
        </div>

        <div className="telemetry-hud__row">
          <span className="telemetry-hud__label">FLIGHT TIME</span>
          <span className="telemetry-hud__value">{formatFlightTime(ft)}</span>
        </div>

        <div className="telemetry-hud__divider" />

        <div className="telemetry-hud__row">
          <span className="telemetry-hud__label">LINK</span>
          <div className="telemetry-hud__status-group">
            <span
              className="telemetry-hud__dot"
              style={{ background: connected ? '#22c55e' : '#ef4444' }}
            />
            <span
              className="telemetry-hud__value"
              style={{ color: connected ? '#22c55e' : '#ef4444' }}
            >
              {connected ? 'CONNECTED' : 'DISCONNECTED'}
            </span>
          </div>
        </div>

        <div className="telemetry-hud__row">
          <span className="telemetry-hud__label">MODE</span>
          <span
            className="telemetry-hud__value"
            style={{ color: flying ? '#60a5fa' : '#4b5563' }}
          >
            {flying ? 'AIRBORNE' : 'GROUNDED'}
          </span>
        </div>
      </div>
    </div>
  )
}
