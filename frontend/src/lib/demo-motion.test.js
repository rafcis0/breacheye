import { test } from 'node:test'
import assert from 'node:assert/strict'
import { demoPose } from './demo-motion.js'
test('demo rises, traverses toward the bed, and stops short of the wall', () => {
  const start = demoPose(0), rise = demoPose(2.3), end = demoPose(14)
  assert.ok(rise.y > start.y + .7)
  assert.ok(end.x > start.x + 2)
  assert.ok(end.z < start.z - 2.5)
  assert.ok(end.z > -2.5)
  assert.deepEqual(demoPose(50), end)
  for (let t = 2.4; t <= 14; t += .1) {
    assert.ok(demoPose(t).z <= demoPose(t - .1).z)
    assert.ok(demoPose(t).y > .9)
  }
})
