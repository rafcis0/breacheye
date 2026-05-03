import { useRef } from 'react'
import { WebSocketProvider } from './contexts/WebSocketContext'
import AppHeader from './components/AppHeader'
import VideoPanel from './components/VideoPanel'
import DetectionOverlay from './components/DetectionOverlay'
import FlightControls from './components/FlightControls'
import TacticalMap from './components/TacticalMap'
import Map3D from './components/Map3D'
import './App.css'

export default function App() {
  const videoFrameRef = useRef(null)

  return (
    <WebSocketProvider>
      {/* Full viewport column flex */}
      <div className="h-screen w-screen flex flex-col overflow-hidden bg-[var(--bg-base)]">

        {/* Header — 48px fixed */}
        <AppHeader />

        {/* Main — flex row, fills remaining height between header and bottom bar */}
        <main className="flex-1 flex flex-row overflow-hidden">

          {/* Zone A — video + detection overlay, left column */}
          <section className="flex-1 min-w-0 p-4">
            <div className="video-overlay-container h-full">
              <VideoPanel frameRef={videoFrameRef} />
              <DetectionOverlay containerRef={videoFrameRef} />
            </div>
          </section>

          {/* Zone B — right sidebar: controls (fixed) + tactical map (flex) */}
          <aside className="w-[320px] flex flex-col flex-shrink-0 p-4 pl-0 gap-3">
            {/* Flight controls — fixed height content */}
            <div className="flex-shrink-0">
              <FlightControls />
            </div>

            {/* Tactical Map — flex-1 fills remaining space */}
            <div className="flex-1 min-h-0">
              <TacticalMap />
            </div>

            {/* 3D Map */}
            <div className="flex-1 min-h-0">
              <Map3D />
            </div>
          </aside>
        </main>

        {/* Zone C — bottom bar, 32px fixed */}
        <footer className="h-8 flex-shrink-0 app__bottom-bar">
          <span className="app__bottom-placeholder">ZONE C · STATUS BAR</span>
        </footer>

      </div>
    </WebSocketProvider>
  )
}
