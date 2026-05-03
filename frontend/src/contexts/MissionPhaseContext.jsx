import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { useWebSocket, CONNECTION_STATE } from './WebSocketContext'

export const PHASE = {
  PRE_FLIGHT: 'PRE_FLIGHT',
  ACTIVE: 'ACTIVE',
  POST_FLIGHT: 'POST_FLIGHT',
}

const MissionPhaseContext = createContext(null)

export function MissionPhaseProvider({ children }) {
  const { data: telemetry, connectionState } = useWebSocket('drone.telemetry')
  const hasFlownRef = useRef(false)
  const [phaseOverride, setPhaseOverride] = useState(null)

  const isConnected = connectionState === CONNECTION_STATE.CONNECTED
  const isFlying = !!(
    telemetry && (telemetry.flying === true || (telemetry.height_cm ?? 0) > 0)
  )

  if (isFlying) {
    hasFlownRef.current = true
  }

  // Reset latch when connection drops so a reconnect starts fresh
  useEffect(() => {
    if (!isConnected) {
      hasFlownRef.current = false
    }
  }, [isConnected])

  let derived
  if (isFlying) {
    derived = PHASE.ACTIVE
  } else if (hasFlownRef.current) {
    derived = PHASE.POST_FLIGHT
  } else {
    derived = PHASE.PRE_FLIGHT
  }

  const phase = phaseOverride ?? derived

  return (
    <MissionPhaseContext.Provider value={{ phase, setPhaseOverride }}>
      {children}
    </MissionPhaseContext.Provider>
  )
}

export function useMissionPhase() {
  const ctx = useContext(MissionPhaseContext)
  if (!ctx) {
    throw new Error('useMissionPhase must be used inside <MissionPhaseProvider>')
  }
  return ctx
}
