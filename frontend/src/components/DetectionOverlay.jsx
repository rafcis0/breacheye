import { useEffect, useRef, useCallback } from 'react'

// NOTE: This component creates its own WebSocket connection to /events.
// When TelemetryHUD (PR #33) is merged, consolidate both into a shared
// useWebSocket hook to avoid duplicate connections.
const WS_URL = 'ws://localhost:8000/events'

// Source resolution for coordinate scaling
const SRC_W = 960
const SRC_H = 720

// POI category colors per CONSTITUTION
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

const THREAT_COLORS = {
  HOT:     '#ef4444',
  WARM:    '#f97316',
  CAUTION: '#eab308',
  CLEAR:   '#22c55e',
  INFO:    '#94a3b8',
}

const DEFAULT_COLOR = '#94a3b8'

const LIFETIME_MS = 2000
const FADE_START_MS = 1500

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

// containerRef points to video-panel__frame — the element that renders the
// actual video. The canvas is a sibling of VideoPanel inside
// .video-overlay-container, so we must compute the frame's position relative
// to its offset parent to place the canvas correctly.
export default function DetectionOverlay({ containerRef }) {
  const canvasRef = useRef(null)
  const ctxRef = useRef(null)
  const detectionsRef = useRef([])
  const rafRef = useRef(null)
  const wsRef = useRef(null)
  const backoffRef = useRef(1000)
  const reconnectRef = useRef(null)

  const drawFrame = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = ctxRef.current
    if (!ctx) return
    const now = Date.now()

    ctx.clearRect(0, 0, canvas.width, canvas.height)

    detectionsRef.current = detectionsRef.current.filter(
      (e) => now - e.arrivedAt < LIFETIME_MS
    )

    if (detectionsRef.current.length === 0) {
      rafRef.current = requestAnimationFrame(drawFrame)
      return
    }

    const scaleX = canvas.width / SRC_W
    const scaleY = canvas.height / SRC_H

    for (const entry of detectionsRef.current) {
      const { detection, arrivedAt } = entry
      const age = now - arrivedAt
      let opacity = 1
      if (age >= FADE_START_MS) {
        opacity = 1 - (age - FADE_START_MS) / (LIFETIME_MS - FADE_START_MS)
      }
      opacity = Math.max(0, Math.min(1, opacity))

      const { category, label, confidence, bbox_2d, threat_level } = detection
      const color = CATEGORY_COLORS[category] ?? DEFAULT_COLOR
      const [r, g, b] = hexToRgb(color)

      const x = bbox_2d.x1 * scaleX
      const y = bbox_2d.y1 * scaleY
      const w = (bbox_2d.x2 - bbox_2d.x1) * scaleX
      const h = (bbox_2d.y2 - bbox_2d.y1) * scaleY

      ctx.save()
      ctx.globalAlpha = opacity

      // Bbox rectangle
      ctx.strokeStyle = color
      ctx.lineWidth = 2
      ctx.strokeRect(x, y, w, h)

      // Label: "{category_code} {label} {confidence}%"
      const pct = Math.round(confidence * 100)
      const labelText = `${category} ${label} ${pct}%`
      ctx.font = '11px monospace'
      ctx.textBaseline = 'bottom'
      const textMetrics = ctx.measureText(labelText)
      const textW = textMetrics.width + 8
      const textH = 16
      const textX = x
      const textY = y - 2

      // Semi-transparent label background
      ctx.fillStyle = `rgba(${r}, ${g}, ${b}, 0.2)`
      ctx.fillRect(textX, textY - textH, textW, textH)

      ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.6)`
      ctx.lineWidth = 1
      ctx.strokeRect(textX, textY - textH, textW, textH)

      ctx.fillStyle = color
      ctx.fillText(labelText, textX + 4, textY - 2)

      // Threat badge — top-right corner of bbox
      const threatColor = THREAT_COLORS[threat_level] ?? DEFAULT_COLOR
      const [tr, tg, tb] = hexToRgb(threatColor)
      const badgeText = threat_level ?? 'INFO'
      const badgeW = ctx.measureText(badgeText).width + 8
      const badgeH = 14
      const badgeX = x + w - badgeW
      const badgeY = y

      ctx.fillStyle = `rgba(${tr}, ${tg}, ${tb}, 0.25)`
      ctx.fillRect(badgeX, badgeY, badgeW, badgeH)

      ctx.strokeStyle = `rgba(${tr}, ${tg}, ${tb}, 0.7)`
      ctx.lineWidth = 1
      ctx.strokeRect(badgeX, badgeY, badgeW, badgeH)

      ctx.font = '9px monospace'
      ctx.textBaseline = 'top'
      ctx.fillStyle = threatColor
      ctx.fillText(badgeText, badgeX + 4, badgeY + 3)

      ctx.restore()
    }

    rafRef.current = requestAnimationFrame(drawFrame)
  }, [])

  // Sync canvas size and position to the video frame element
  useEffect(() => {
    const canvas = canvasRef.current
    const frameEl = containerRef?.current
    if (!canvas || !frameEl) return

    ctxRef.current = canvas.getContext('2d')

    function syncToFrame() {
      const frameRect = frameEl.getBoundingClientRect()
      const parentRect = canvas.offsetParent?.getBoundingClientRect() ?? frameRect

      canvas.style.left = `${frameRect.left - parentRect.left}px`
      canvas.style.top = `${frameRect.top - parentRect.top}px`
      canvas.width = Math.round(frameRect.width)
      canvas.height = Math.round(frameRect.height)
    }

    syncToFrame()

    const ro = new ResizeObserver(syncToFrame)
    ro.observe(frameEl)

    return () => ro.disconnect()
  }, [containerRef])

  // WebSocket subscription
  useEffect(() => {
    let ws

    function connect() {
      ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        backoffRef.current = 1000
      }

      ws.onmessage = (event) => {
        try {
          const envelope = JSON.parse(event.data)
          if (envelope.topic !== 'drone.detections') return
          const msg = envelope.message
          if (!Array.isArray(msg?.detections)) return

          const now = Date.now()
          const incoming = msg.detections.map((detection) => ({
            detection,
            arrivedAt: now,
          }))

          // Refresh timestamps for existing IDs; append new ones
          detectionsRef.current = [
            ...detectionsRef.current.filter(
              (e) => !incoming.some((n) => n.detection.id === e.detection.id)
            ),
            ...incoming,
          ]
        } catch {
          // Malformed frame — skip
        }
      }

      ws.onclose = () => {
        reconnectRef.current = setTimeout(connect, backoffRef.current)
        backoffRef.current = Math.min(backoffRef.current * 2, 30000)
      }

      ws.onerror = () => {}
    }

    connect()

    return () => {
      clearTimeout(reconnectRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
      }
    }
  }, [])

  // Animation loop
  useEffect(() => {
    rafRef.current = requestAnimationFrame(drawFrame)
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    }
  }, [drawFrame])

  return (
    <canvas
      ref={canvasRef}
      className="detection-overlay__canvas"
      aria-hidden="true"
    />
  )
}
