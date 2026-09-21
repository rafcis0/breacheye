import { test } from 'node:test'
import assert from 'node:assert/strict'
import { formatFlightTime } from './telemetry.js'
test('flight timer renders whole seconds and rejects invalid telemetry', () => {
  assert.equal(formatFlightTime(61.9), '01:01')
  assert.equal(formatFlightTime(-1), '--:--')
  assert.equal(formatFlightTime(NaN), '--:--')
  assert.equal(formatFlightTime(null), '--:--')
})
