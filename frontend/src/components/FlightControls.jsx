import { useState, useRef, useCallback } from 'react'

const COMMAND_URL = '/api/commands'
const HOLD_MS = 500

async function postCommand(type) {
  const res = await fetch(COMMAND_URL, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ type, issued_by: 'frontend_operator' }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

function HoldButton({ label, className, disabled, onActivate }) {
  const timerRef = useRef(null)
  const startRef = useRef(null)
  const rafRef = useRef(null)
  const [progress, setProgress] = useState(0)

  const cancel = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    startRef.current = null
    setProgress(0)
  }, [])

  const tick = useCallback(() => {
    if (startRef.current === null) return
    const elapsed = Date.now() - startRef.current
    const pct = Math.min(elapsed / HOLD_MS, 1)
    setProgress(pct)
    if (pct < 1) {
      rafRef.current = requestAnimationFrame(tick)
    }
  }, [])

  const onPointerDown = useCallback((e) => {
    if (disabled) return
    e.currentTarget.setPointerCapture(e.pointerId)
    startRef.current = Date.now()
    setProgress(0)
    rafRef.current = requestAnimationFrame(tick)
    timerRef.current = setTimeout(() => {
      cancel()
      onActivate()
    }, HOLD_MS)
  }, [disabled, tick, cancel, onActivate])

  const onPointerUp = useCallback(() => {
    cancel()
  }, [cancel])

  return (
    <button
      className={`flight-controls__button ${className}`}
      type="button"
      disabled={disabled}
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
      style={{ position: 'relative', overflow: 'hidden', userSelect: 'none' }}
    >
      {progress > 0 && (
        <span
          style={{
            position: 'absolute',
            left: 0,
            bottom: 0,
            height: '3px',
            width: `${progress * 100}%`,
            background: 'rgba(255,255,255,0.6)',
            transition: 'none',
            borderRadius: '0 2px 0 0',
          }}
        />
      )}
      {label}
    </button>
  )
}

export default function FlightControls() {
  const [landBusy, setLandBusy] = useState(false)
  const [emergencyBusy, setEmergencyBusy] = useState(false)
  const [banner, setBanner] = useState(null)
  const bannerTimerRef = useRef(null)

  function showBanner(msg, color) {
    if (bannerTimerRef.current) clearTimeout(bannerTimerRef.current)
    setBanner({ msg, color })
    bannerTimerRef.current = setTimeout(() => setBanner(null), 3000)
  }

  const sendLand = useCallback(async () => {
    setLandBusy(true)
    try {
      await postCommand('land')
      showBanner('LAND COMMAND SENT — drone descending', 'var(--color-accent-warning)')
    } catch {
      showBanner('LAND FAILED', 'var(--color-accent-danger)')
    } finally {
      setLandBusy(false)
    }
  }, [])

  const sendEmergency = useCallback(async () => {
    setEmergencyBusy(true)
    try {
      await postCommand('emergency')
      showBanner('EMERGENCY STOP — motors killed', 'var(--color-accent-danger)')
    } catch {
      showBanner('EMERGENCY FAILED', 'var(--color-accent-danger)')
    } finally {
      setEmergencyBusy(false)
    }
  }, [])

  return (
    <div className="flight-controls">
      <div className="flight-controls__header">
        <span className="flight-controls__title">OPERATOR CONTROL</span>
        <span className="flight-controls__last">HOLD TO ACTIVATE</span>
      </div>

      {banner && (
        <div
          style={{
            padding: '8px 14px',
            fontFamily: 'var(--font-mono)',
            fontSize: '10px',
            fontWeight: 700,
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            color: banner.color,
            borderBottom: `1px solid ${banner.color}`,
            background: 'rgba(0,0,0,0.3)',
          }}
        >
          {banner.msg}
        </div>
      )}

      <div className="flight-controls__buttons">
        <HoldButton
          label="LAND"
          className="flight-controls__button--land"
          disabled={landBusy}
          onActivate={sendLand}
        />
        <HoldButton
          label="EMERGENCY"
          className="flight-controls__button--emergency"
          disabled={emergencyBusy}
          onActivate={sendEmergency}
        />
      </div>
    </div>
  )
}
