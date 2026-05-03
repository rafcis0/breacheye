import { useEffect, useRef, useState } from 'react'

const WS_URL = `ws://${window.location.host}/api/events`
const HEALTH_URL = '/api/health'
const POLL_INTERVAL_MS = 2000
const RECONNECT_DELAY_MS = 1000

function batteryColor(battery) {
  if (battery === null || battery === undefined) return '#6b7280'
  if (battery > 50) return '#22c55e'
  if (battery >= 20) return '#eab308'
  return '#ef4444'
}

function formatFlightTime(seconds) {
  if (seconds === null || seconds === undefined) return '--:--'
  const m = Math.floor(seconds / 60).toString().padStart(2, '0')
  const s = (seconds % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}

export default function TelemetryHUD() {
  const [telemetry, setTelemetry] = useState(null)
  const [wsConnected, setWsConnected] = useState(false)
  const wsRef = useRef(null)
  const pollRef = useRef(null)
  const reconnectRef = useRef(null)

  function startPolling() {
    if (pollRef.current) return
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(HEALTH_URL)
        if (res.ok) {
          const data = await res.json()
          if (data.telemetry) setTelemetry(data.telemetry)
        }
      } catch {
        // server not yet up, keep trying
      }
    }, POLL_INTERVAL_MS)
  }

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  function connect() {
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      setWsConnected(true)
      stopPolling()
    }

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data)
        if (msg.topic === 'drone.telemetry' && msg.message) {
          setTelemetry(msg.message)
        }
      } catch {
        // malformed message, ignore
      }
    }

    ws.onclose = () => {
      setWsConnected(false)
      startPolling()
      reconnectRef.current = setTimeout(connect, RECONNECT_DELAY_MS)
    }

    ws.onerror = () => {
      ws.close()
    }
  }

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectRef.current)
      stopPolling()
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
      }
    }
  }, [])

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
          {wsConnected ? 'WS' : 'POLL'}
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
