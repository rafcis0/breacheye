/**
 * Shared telemetry display utilities.
 * Used by AppHeader and TelemetryHUD.
 */

export function batteryColor(level) {
  if (level === null || level === undefined) return undefined
  if (level > 50) return 'var(--color-status-normal)'
  if (level >= 20) return 'var(--color-status-caution)'
  return 'var(--color-status-critical)'
}

export function formatFlightTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '--:--'
  seconds = Math.floor(seconds)
  const m = Math.floor(seconds / 60).toString().padStart(2, '0')
  const s = (seconds % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}
