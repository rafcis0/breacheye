import { useRef } from 'react'
import { WebSocketProvider } from './contexts/WebSocketContext'
import { MissionPhaseProvider, useMissionPhase, PHASE } from './contexts/MissionPhaseContext'
import AppHeader from './components/AppHeader'
import BottomBar from './components/BottomBar'
import VideoPanel from './components/VideoPanel'
import DetectionOverlay from './components/DetectionOverlay'
import FlightControls from './components/FlightControls'
import TacticalMap from './components/TacticalMap'
import Map3D from './components/Map3D'
import './App.css'

function PreFlightStatus() {
  return (
    <div
      className="glass-panel flex flex-col items-center justify-center gap-3 p-5 flex-shrink-0"
      style={{ borderColor: 'var(--color-status-standby, rgba(96,165,250,0.3))' }}
    >
      <span
        className="font-mono text-[11px] font-semibold tracking-[0.14em] uppercase"
        style={{ color: 'var(--color-status-standby, #60a5fa)' }}
      >
        PREFLIGHT
      </span>
      <span
        className="font-mono text-[10px] tracking-[0.1em] uppercase"
        style={{ color: 'rgba(255,255,255,0.45)' }}
      >
        Waiting for launch
      </span>
    </div>
  )
}

function PostFlightActions({ flightTime, poiCount }) {
  return (
    <div
      className="glass-panel flex flex-col gap-3 p-4 flex-shrink-0"
    >
      <span
        className="font-mono text-[11px] font-semibold tracking-[0.14em] uppercase"
        style={{ color: 'var(--color-accent-blue)' }}
      >
        MISSION COMPLETE
      </span>

      {/* Summary row */}
      <div className="flex gap-4">
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[9px] tracking-[0.1em] uppercase" style={{ color: 'rgba(255,255,255,0.4)' }}>
            FLIGHT TIME
          </span>
          <span className="font-mono text-[12px] font-semibold" style={{ color: 'rgba(255,255,255,0.85)' }}>
            {flightTime ?? '--:--'}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[9px] tracking-[0.1em] uppercase" style={{ color: 'rgba(255,255,255,0.4)' }}>
            TOTAL POI
          </span>
          <span className="font-mono text-[12px] font-semibold" style={{ color: 'rgba(255,255,255,0.85)' }}>
            {poiCount ?? 0}
          </span>
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex gap-2">
        <button
          type="button"
          className="flex-1 py-2 rounded font-mono text-[11px] font-extrabold tracking-[0.12em] uppercase"
          style={{
            border: '1px solid var(--color-accent-blue)',
            background: 'transparent',
            color: 'var(--color-accent-blue)',
            cursor: 'pointer',
          }}
        >
          VIEW REPLAY
        </button>
        <button
          type="button"
          className="flex-1 py-2 rounded font-mono text-[11px] font-extrabold tracking-[0.12em] uppercase"
          style={{
            border: '1px solid var(--color-accent-blue)',
            background: 'transparent',
            color: 'var(--color-accent-blue)',
            cursor: 'pointer',
          }}
        >
          EXPORT REPORT
        </button>
      </div>
    </div>
  )
}

function AppLayout() {
  const videoFrameRef = useRef(null)
  const { phase } = useMissionPhase()

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-[var(--bg-base)]">

      {/* Header — 48px fixed */}
      <AppHeader />

      {/* Main — flex row, fills remaining height between header and bottom bar */}
      <main className="flex-1 flex flex-row overflow-hidden">

        {/* Zone A — primary view, left column */}
        <section className="flex-1 min-w-0 p-4">
          {phase === PHASE.POST_FLIGHT ? (
            <div className="h-full glass-panel overflow-hidden">
              <Map3D />
            </div>
          ) : (
            <div className="video-overlay-container h-full">
              <VideoPanel frameRef={videoFrameRef} />
              <DetectionOverlay containerRef={videoFrameRef} />
            </div>
          )}
        </section>

        {/* Zone B — right sidebar */}
        <aside className="w-[320px] flex flex-col flex-shrink-0 p-4 pl-0 gap-3">

          {/* Flight controls or phase card */}
          {phase === PHASE.ACTIVE && (
            <div className="flex-shrink-0 glass-panel overflow-hidden">
              <FlightControls />
            </div>
          )}
          {phase === PHASE.PRE_FLIGHT && <PreFlightStatus />}
          {phase === PHASE.POST_FLIGHT && <PostFlightActions />}

          {/* Tactical Map — always visible */}
          <div className="flex-1 min-h-0 glass-panel overflow-hidden">
            <TacticalMap />
          </div>

          {/* 3D Map — only in ACTIVE phase (sidebar position) */}
          {phase === PHASE.ACTIVE && (
            <div className="flex-1 min-h-0 glass-panel overflow-hidden">
              <Map3D />
            </div>
          )}
        </aside>
      </main>

      {/* Zone C — bottom bar, 32px fixed */}
      <BottomBar phase={phase} />

    </div>
  )
}

export default function App() {
  return (
    <WebSocketProvider>
      <MissionPhaseProvider>
        <AppLayout />
      </MissionPhaseProvider>
    </WebSocketProvider>
  )
}
