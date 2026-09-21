// Approximate the recorded rise, traverse over the bed, and approach to the wall.
const keys = [
  { t: 0, x: -.8, y: .48, z: 1.4, yaw: -.25 },
  { t: 2.3, x: -.72, y: 1.3, z: 1.25, yaw: -.18 },
  { t: 6, x: -.1, y: 1.35, z: .7, yaw: -.05 },
  { t: 10, x: .9, y: 1.4, z: -.45, yaw: .03 },
  { t: 14, x: 1.45, y: 1.4, z: -1.6, yaw: 0 },
]
export function demoPose(seconds) {
  const t = Math.max(0, Math.min(14, Number.isFinite(seconds) ? seconds : 0))
  const end = keys.findIndex(k => k.t >= t)
  const a = keys[Math.max(0, end - 1)], b = keys[Math.max(0, end)]
  const u = a === b ? 0 : (t - a.t) / (b.t - a.t)
  const smooth = u * u * (3 - 2 * u)
  const pose = Object.fromEntries(['x', 'y', 'z', 'yaw'].map(k => [k, a[k] + (b[k] - a[k]) * smooth]))
  return { ...pose, stage: t < 2.3 ? 'CLIMB TO SCAN HEIGHT' : t < 6 ? 'ADVANCE TOWARD BED' : t < 10 ? 'TRAVERSE ABOVE BED' : 'APPROACH WALL · SLOW FOR CLEARANCE' }
}
