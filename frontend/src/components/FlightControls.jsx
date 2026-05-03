import { useState } from 'react'

const COMMAND_URL = '/api/commands'

async function postCommand(type) {
  const res = await fetch(COMMAND_URL, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ type, issued_by: 'frontend_operator' }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export default function FlightControls() {
  const [busy, setBusy] = useState(null)
  const [last, setLast] = useState(null)

  async function send(type) {
    setBusy(type)
    try {
      const result = await postCommand(type)
      setLast(`${type.toUpperCase()} ${result.status ?? 'sent'}`)
    } catch (err) {
      setLast(`${type.toUpperCase()} FAILED`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flight-controls">
      <div className="flight-controls__header">
        <span className="flight-controls__title">OPERATOR CONTROL</span>
        <span className="flight-controls__last">{last ?? 'READY'}</span>
      </div>
      <div className="flight-controls__buttons">
        <button
          className="flight-controls__button flight-controls__button--land"
          type="button"
          disabled={busy !== null}
          onClick={() => send('land')}
        >
          LAND
        </button>
        <button
          className="flight-controls__button flight-controls__button--emergency"
          type="button"
          disabled={busy !== null}
          onClick={() => send('emergency')}
        >
          EMERGENCY
        </button>
      </div>
    </div>
  )
}
