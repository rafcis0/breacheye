import { demoPose } from './demo-motion.js'
// Explicit opt-in. Demo data never opens the hardware WebSocket.
export const DEMO_MODE = new URLSearchParams(window.location.search).get('demo') === '1'
let demoTime = 0
export function startDemo(publish) {
  const send = (time) => {
    demoTime = Math.max(0, Number(time) || 0)
    publish('drone.detections', { detections: demoTime < 3 ? [] : [
      { id: 'demo-bed', category: 'ROOM', label: 'bed (simulated)', confidence: .94, threat_level: 'INFO', bbox_2d: { x1: 530, y1: 350, x2: 880, y2: 600 } },
      ...(demoTime < 7 ? [] : [{ id: 'demo-door', category: 'T1-01', label: 'door (simulated)', confidence: .91, threat_level: 'INFO', bbox_2d: { x1: 100, y1: 150, x2: 280, y2: 520 } }]),
    ] })
    const pose = demoPose(demoTime)
    publish('drone.telemetry', {
      connected: true, flying: true, battery: 87 - Math.floor(demoTime / 7),
      height_cm: Math.round(pose.y * 100),
      flight_time_s: demoTime, demo_time_s: demoTime,
      x_cm: 480 + pose.x * 90, y_cm: 360 + pose.z * 75,
    })
  }
  const onSeek = (event) => send(event.detail)
  window.addEventListener('breacheye:demo-time', onSeek)
  send(0)
  const start = performance.now()
  const manual = new URLSearchParams(window.location.search).get('capture') === '1'
  const timer = manual ? null : setInterval(() => send((performance.now() - start) / 1000), 100)
  return () => { clearInterval(timer); window.removeEventListener('breacheye:demo-time', onSeek) }
}
export function demoCloud() {
  const points = []
  const progress = Math.min(1, .15 + demoTime / 12)
  for (let i = 0; i < 2400 * progress; i++) {
    const u = (i % 60) / 59, v = Math.floor(i / 60) / 39
    points.push({ x: (u - .5) * 1.2, y: .4, z: v * .65 - .32, intensity: .6 })
    points.push({ x: -.6, y: (u - .5) * .8, z: v * .65 - .32, intensity: .4 })
    points.push({ x: (u - .5) * 1.2, y: (v - .5) * .8, z: -.32, intensity: .8 })
  }
  return { source: 'simulation', points }
}
