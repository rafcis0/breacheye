import VideoPanel from './components/VideoPanel'
import PlaceholderCard from './components/PlaceholderCard'
import TelemetryHUD from './components/TelemetryHUD'
import './App.css'

export default function App() {
  return (
    <div className="app">
      <header className="app__header">
        <div className="app__header-left">
          <span className="app__logo">BREACHEYE</span>
          <span className="app__tagline">Autonomous Indoor Mapping · NatSec 2026</span>
        </div>
        <div className="app__header-right">
          <span className="app__badge">TACTICAL COP</span>
        </div>
      </header>

      <main className="app__body">
        <section className="app__video">
          <VideoPanel />
        </section>

        <aside className="app__sidebar">
          <TelemetryHUD />
          <PlaceholderCard label="DETECTION OVERLAY" ticket="23" />
          <PlaceholderCard label="TACTICAL MAP" ticket="25" />
        </aside>
      </main>
    </div>
  )
}
