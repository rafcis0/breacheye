import { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react'

const WS_URL = 'ws://127.0.0.1:8000/events'

// Connection states
export const CONNECTION_STATE = {
  CONNECTED: 'connected',
  RECONNECTING: 'reconnecting',
  DISCONNECTED: 'disconnected',
}

const WebSocketContext = createContext(null)

/**
 * Provides a single shared WebSocket connection to all children.
 * Components subscribe by topic; only messages matching their topic are
 * delivered to their callbacks.
 */
export function WebSocketProvider({ children }) {
  const [connectionState, setConnectionState] = useState(CONNECTION_STATE.DISCONNECTED)
  const wsRef = useRef(null)
  const backoffRef = useRef(1000)
  const reconnectTimerRef = useRef(null)
  // Map of topic -> Set of listener callbacks
  const listenersRef = useRef(new Map())
  // Latest data per topic, so late-subscribing components get the last value
  const latestRef = useRef(new Map())

  const subscribe = useCallback((topic, callback) => {
    if (!listenersRef.current.has(topic)) {
      listenersRef.current.set(topic, new Set())
    }
    listenersRef.current.get(topic).add(callback)

    // Deliver the latest cached value immediately if available
    if (latestRef.current.has(topic)) {
      callback(latestRef.current.get(topic))
    }

    return () => {
      const set = listenersRef.current.get(topic)
      if (set) {
        set.delete(callback)
        if (set.size === 0) listenersRef.current.delete(topic)
      }
    }
  }, [])

  useEffect(() => {
    function connect() {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws
      setConnectionState(CONNECTION_STATE.RECONNECTING)

      ws.onopen = () => {
        backoffRef.current = 1000
        setConnectionState(CONNECTION_STATE.CONNECTED)
      }

      ws.onmessage = (event) => {
        try {
          const envelope = JSON.parse(event.data)
          const { topic, message } = envelope
          if (!topic) return

          latestRef.current.set(topic, message)

          const callbacks = listenersRef.current.get(topic)
          if (callbacks) {
            for (const cb of callbacks) {
              cb(message)
            }
          }
        } catch {
          // Malformed frame — skip
        }
      }

      ws.onclose = () => {
        setConnectionState(CONNECTION_STATE.RECONNECTING)
        reconnectTimerRef.current = setTimeout(() => {
          backoffRef.current = Math.min(backoffRef.current * 2, 30000)
          connect()
        }, backoffRef.current)
      }

      ws.onerror = () => {
        // onclose fires after onerror; handled there
      }
    }

    connect()

    return () => {
      clearTimeout(reconnectTimerRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
      }
      setConnectionState(CONNECTION_STATE.DISCONNECTED)
    }
  }, [])

  return (
    <WebSocketContext.Provider value={{ connectionState, subscribe }}>
      {children}
    </WebSocketContext.Provider>
  )
}

/**
 * Subscribe to a single WebSocket topic.
 *
 * @param {string} topic  e.g. "drone.telemetry", "drone.detections", "drone.position"
 * @returns {{ data: any, connectionState: string }}
 */
export function useWebSocket(topic) {
  const ctx = useContext(WebSocketContext)
  if (!ctx) {
    throw new Error('useWebSocket must be used inside <WebSocketProvider>')
  }

  const { connectionState, subscribe } = ctx
  const [data, setData] = useState(null)

  useEffect(() => {
    const unsub = subscribe(topic, setData)
    return unsub
  }, [topic, subscribe])

  return { data, connectionState }
}
