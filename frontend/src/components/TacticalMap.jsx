import { useEffect, useRef, useCallback, useState } from 'react'
import { useWebSocket } from '../contexts/WebSocketContext'

const SRC_W = 960
const SRC_H = 720
const DEDUP_THRESHOLD = 0.05
const MAX_MARKERS = 200

const CATEGORY_COLORS = {
  'T1-01': '#60a5fa',
  'T1-02': '#f87171',
  'T1-03': '#818cf8',
  'T2-02': '#f87171',
  'T2-03': '#fbbf24',
  'T3-01': '#a78bfa',
  'T4-01': '#fb923c',
  'ROOM':  '#2dd4bf',
}

const DEFAULT_COLOR = '#94a3b8'

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function drawGrid(ctx, w, h) {
  const CELL = 40
  ctx.clearRect(0, 0, w, h)
  ctx.fillStyle = '#0a0a0f'
  ctx.fillRect(0, 0, w, h)

  ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)'
  ctx.lineWidth = 1

  for (let x = 0; x <= w; x += CELL) {
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, h)
    ctx.stroke()
  }
  for (let y = 0; y <= h; y += CELL) {
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(w, y)
    ctx.stroke()
  }
}

function drawLegend(ctx, w, h) {
  const PAD = 8
  const DOT_R = 4
  const LINE_H = 16
  const FONT_SIZE = 10
  const entries = Object.entries(CATEGORY_COLORS)

  ctx.save()
  ctx.font = `${FONT_SIZE}px monospace`

  // Measure widest label to size the background rect
  let maxLabelW = 0
  for (const [cat] of entries) {
    const tw = ctx.measureText(cat).width
    if (tw > maxLabelW) maxLabelW = tw
  }

  const rectW = PAD * 2 + DOT_R * 2 + 6 + maxLabelW
  const rectH = PAD * 2 + entries.length * LINE_H

  const rx = PAD
  const ry = h - rectH - PAD

  // Background
  ctx.fillStyle = 'rgba(10, 10, 15, 0.72)'
  ctx.beginPath()
  ctx.roundRect(rx, ry, rectW, rectH, 3)
  ctx.fill()

  // Entries
  for (let i = 0; i < entries.length; i++) {
    const [cat, color] = entries[i]
    const cx = rx + PAD + DOT_R
    const cy = ry + PAD + i * LINE_H + LINE_H / 2

    ctx.beginPath()
    ctx.arc(cx, cy, DOT_R, 0, Math.PI * 2)
    ctx.fillStyle = color
    ctx.fill()

    ctx.fillStyle = 'rgba(255, 255, 255, 0.7)'
    ctx.textBaseline = 'middle'
    ctx.fillText(cat, cx + DOT_R + 6, cy)
  }

  ctx.restore()
}

function drawCompass(ctx, w) {
  const SIZE = 24
  const PAD = 10
  const cx = w - PAD - SIZE / 2
  const cy = PAD + SIZE / 2

  ctx.save()

  // Background circle
  ctx.beginPath()
  ctx.arc(cx, cy, SIZE / 2, 0, Math.PI * 2)
  ctx.fillStyle = 'rgba(10, 10, 15, 0.72)'
  ctx.fill()

  // North triangle
  const triH = 8
  const triW = 5
  ctx.beginPath()
  ctx.moveTo(cx, cy - SIZE / 2 + 4)
  ctx.lineTo(cx - triW / 2, cy - SIZE / 2 + 4 + triH)
  ctx.lineTo(cx + triW / 2, cy - SIZE / 2 + 4 + triH)
  ctx.closePath()
  ctx.fillStyle = '#ffffff'
  ctx.fill()

  // "N" label
  ctx.font = '8px monospace'
  ctx.fillStyle = '#ffffff'
  ctx.textBaseline = 'middle'
  ctx.textAlign = 'center'
  ctx.fillText('N', cx, cy + SIZE / 2 - 6)

  ctx.restore()
}

export default function TacticalMap() {
  const canvasRef = useRef(null)
  const markersRef = useRef([])
  const droneRef = useRef(null)
  const hoveredRef = useRef(null)
  const dirtyRef = useRef(true)
  const rafRef = useRef(null)
  const prevTelemetryRef = useRef(null)
  const [poiCount, setPoiCount] = useState(0)

  const { data: detectionsData } = useWebSocket('drone.detections')
  const { data: telemetryData } = useWebSocket('drone.telemetry')

  const render = useCallback(() => {
    rafRef.current = requestAnimationFrame(render)

    if (!dirtyRef.current) return
    dirtyRef.current = false

    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const w = canvas.width
    const h = canvas.height

    drawGrid(ctx, w, h)

    // Draw markers
    for (const marker of markersRef.current) {
      const px = marker.x * w
      const py = marker.y * h
      const radius = 4 + marker.confidence * 4
      const color = CATEGORY_COLORS[marker.category] ?? DEFAULT_COLOR
      const [r, g, b] = hexToRgb(color)
      const isHovered = hoveredRef.current?.id === marker.id

      ctx.save()
      ctx.beginPath()
      ctx.arc(px, py, radius + (isHovered ? 3 : 0), 0, Math.PI * 2)
      ctx.fillStyle = `rgba(${r}, ${g}, ${b}, 0.25)`
      ctx.fill()

      ctx.beginPath()
      ctx.arc(px, py, radius, 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.fill()
      ctx.restore()
    }

    // Draw drone indicator
    if (droneRef.current) {
      const { x, y } = droneRef.current
      const px = x * w
      const py = y * h

      ctx.save()
      ctx.beginPath()
      ctx.arc(px, py, 7, 0, Math.PI * 2)
      ctx.fillStyle = 'rgba(52, 211, 153, 0.2)'
      ctx.fill()

      ctx.beginPath()
      ctx.arc(px, py, 4, 0, Math.PI * 2)
      ctx.fillStyle = '#34d399'
      ctx.shadowColor = '#34d399'
      ctx.shadowBlur = 8
      ctx.fill()
      ctx.restore()
    } else {
      // No position data — pulsing dot at center
      const pulse = 0.5 + 0.5 * Math.sin(Date.now() / 500)
      const px = w / 2
      const py = h / 2

      ctx.save()
      ctx.beginPath()
      ctx.arc(px, py, 5, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(52, 211, 153, ${0.3 + pulse * 0.4})`
      ctx.shadowColor = '#34d399'
      ctx.shadowBlur = 6 + pulse * 6
      ctx.fill()
      ctx.restore()

      // Force redraw each frame while no position so the pulse animates
      dirtyRef.current = true
    }

    // Draw tooltip
    if (hoveredRef.current) {
      const { x, y, label, category, confidence } = hoveredRef.current
      const px = x * w
      const py = y * h
      const pct = Math.round(confidence * 100)
      const text = `${category} ${label} ${pct}%`

      ctx.save()
      ctx.font = '11px monospace'
      const textW = ctx.measureText(text).width + 12
      const textH = 20
      let tx = px + 10
      let ty = py - textH - 6

      // Keep tooltip inside canvas
      if (tx + textW > w) tx = px - textW - 10
      if (ty < 0) ty = py + 6

      ctx.fillStyle = 'rgba(10, 10, 15, 0.9)'
      ctx.strokeStyle = CATEGORY_COLORS[category] ?? DEFAULT_COLOR
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.roundRect(tx, ty, textW, textH, 3)
      ctx.fill()
      ctx.stroke()

      ctx.fillStyle = CATEGORY_COLORS[category] ?? DEFAULT_COLOR
      ctx.textBaseline = 'middle'
      ctx.fillText(text, tx + 6, ty + textH / 2)
      ctx.restore()
    }

    // Overlay elements — drawn last so they're always on top
    drawLegend(ctx, w, h)
    drawCompass(ctx, w)
  }, [])

  // Canvas resize observer
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ro = new ResizeObserver(() => {
      canvas.width = canvas.offsetWidth
      canvas.height = canvas.offsetHeight
      dirtyRef.current = true
    })
    ro.observe(canvas)
    canvas.width = canvas.offsetWidth
    canvas.height = canvas.offsetHeight
    return () => ro.disconnect()
  }, [])

  // Mouse hit-testing for tooltip
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    function onMouseMove(e) {
      const rect = canvas.getBoundingClientRect()
      const mx = (e.clientX - rect.left) / rect.width
      const my = (e.clientY - rect.top) / rect.height
      const hitPx = 10 / rect.width
      const hitPy = 10 / rect.height

      let found = null
      for (const marker of markersRef.current) {
        if (Math.hypot(mx - marker.x, my - marker.y) < Math.max(hitPx, hitPy)) {
          found = marker
          break
        }
      }

      if (found?.id !== hoveredRef.current?.id) {
        hoveredRef.current = found
        dirtyRef.current = true
      }
    }

    function onMouseLeave() {
      if (hoveredRef.current !== null) {
        hoveredRef.current = null
        dirtyRef.current = true
      }
    }

    canvas.addEventListener('mousemove', onMouseMove)
    canvas.addEventListener('mouseleave', onMouseLeave)
    return () => {
      canvas.removeEventListener('mousemove', onMouseMove)
      canvas.removeEventListener('mouseleave', onMouseLeave)
    }
  }, [])

  // Handle detections from shared WebSocket context
  useEffect(() => {
    const msg = detectionsData
    if (!Array.isArray(msg?.detections)) return

    for (const det of msg.detections) {
      const { id, category, label, confidence, bbox_2d, threat_level } = det
      if (!bbox_2d) continue

      const cx = ((bbox_2d.x1 + bbox_2d.x2) / 2) / SRC_W
      const cy = ((bbox_2d.y1 + bbox_2d.y2) / 2) / SRC_H

      const existing = markersRef.current.findIndex(
        (m) => m.category === category &&
          Math.hypot(cx - m.x, cy - m.y) < DEDUP_THRESHOLD
      )

      const marker = { id, x: cx, y: cy, category, label, confidence, threat_level }

      if (existing >= 0) {
        markersRef.current[existing] = marker
      } else {
        markersRef.current.push(marker)
        if (markersRef.current.length > MAX_MARKERS) {
          markersRef.current.shift()
        }
      }
    }

    setPoiCount(markersRef.current.length)
    dirtyRef.current = true
  }, [detectionsData])

  // Handle telemetry from shared WebSocket context
  useEffect(() => {
    const msg = telemetryData
    if (!msg) return

    const prev = prevTelemetryRef.current
    prevTelemetryRef.current = msg

    if (msg.x_cm !== undefined && msg.y_cm !== undefined) {
      droneRef.current = {
        x: Math.max(0, Math.min(1, msg.x_cm / SRC_W)),
        y: Math.max(0, Math.min(1, msg.y_cm / SRC_H)),
      }
    } else if (prev && msg.vx !== undefined && msg.vy !== undefined) {
      const cur = droneRef.current ?? { x: 0.5, y: 0.5 }
      droneRef.current = {
        x: Math.max(0, Math.min(1, cur.x + msg.vx * 0.01)),
        y: Math.max(0, Math.min(1, cur.y + msg.vy * 0.01)),
      }
    }

    dirtyRef.current = true
  }, [telemetryData])

  // Render loop
  useEffect(() => {
    rafRef.current = requestAnimationFrame(render)
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    }
  }, [render])

  return (
    <div className="tactical-map">
      <div className="tactical-map__header">
        <span className="tactical-map__title">
          TACTICAL MAP · {poiCount} POI
        </span>
      </div>
      <canvas ref={canvasRef} className="tactical-map__canvas" />
    </div>
  )
}
