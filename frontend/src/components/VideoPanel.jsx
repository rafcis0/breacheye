import { useState, useCallback, useRef, useEffect } from 'react'

const MJPEG_URL = '/api/video.mjpeg'

export default function VideoPanel() {
  const [hasSignal, setHasSignal] = useState(true)
  const retryRef = useRef(null)

  const clearRetry = useCallback(() => {
    if (retryRef.current !== null) {
      clearInterval(retryRef.current)
      retryRef.current = null
    }
  }, [])

  const handleError = useCallback(() => {
    setHasSignal(false)
    if (retryRef.current === null) {
      retryRef.current = setInterval(() => {
        setHasSignal(true)
      }, 3000)
    }
  }, [])

  const handleLoad = useCallback(() => {
    setHasSignal(true)
    clearRetry()
  }, [clearRetry])

  useEffect(() => {
    return () => clearRetry()
  }, [clearRetry])

  return (
    <div className="video-panel">
      <div className="video-panel__header">
        <span className="video-panel__title">LIVE FEED</span>
        <div className="video-panel__status">
          <span
            className={`video-panel__dot ${hasSignal ? 'video-panel__dot--live' : 'video-panel__dot--dead'}`}
          />
          <span className="video-panel__status-text">
            {hasSignal ? 'SIGNAL ACTIVE' : 'NO SIGNAL'}
          </span>
        </div>
      </div>

      <div className="video-panel__frame">
        {hasSignal ? (
          <img
            src={MJPEG_URL}
            alt="Drone MJPEG feed"
            className="video-panel__stream"
            onError={handleError}
            onLoad={handleLoad}
          />
        ) : (
          <div className="video-panel__nosignal">
            <div className="video-panel__nosignal-icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M2 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10S2 17.523 2 12z" />
                <path d="M9 9l6 6M15 9l-6 6" />
              </svg>
            </div>
            <div className="video-panel__nosignal-label">NO SIGNAL</div>
            <div className="video-panel__nosignal-sub">
              Waiting for drone feed on :8000
            </div>
          </div>
        )}
      </div>

      <div className="video-panel__footer">
        <span className="video-panel__meta">DJI TELLO · 960×720 · 30 FPS</span>
        <span className="video-panel__source">{MJPEG_URL}</span>
      </div>
    </div>
  )
}
