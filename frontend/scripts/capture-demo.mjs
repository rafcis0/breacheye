import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'

const output = process.argv[2] ?? '../demo/generated/frontend-frames'
const duration = Number(process.argv[3] ?? 14)
const fps = 30
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true,
  ...(process.env.DEMO_BROWSER ? { executablePath: process.env.DEMO_BROWSER } : {}),
})
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = [], hardwareRequests = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('request', r => { if (new URL(r.url()).pathname.startsWith('/api/')) hardwareRequests.push(r.url()) })
  page.on('websocket', ws => { if (new URL(ws.url()).pathname !== '/') hardwareRequests.push(ws.url()) })
  await page.goto(`${process.env.DEMO_URL ?? 'http://127.0.0.1:5173'}/?demo=1&capture=1`)
  await page.locator('.demo-room__scene canvas').waitFor()
  await page.locator('.map3d__viewport canvas').waitFor()
  await page.evaluate(() => document.fonts.ready)
  assert.equal(await page.locator('header').evaluate(e => getComputedStyle(e).paddingLeft), '24px')
  assert.ok(await page.locator('.tactical-map__canvas').evaluate(e => e.getBoundingClientRect().bottom <= e.parentElement.getBoundingClientRect().bottom), 'Tactical map canvas fits its panel')
  // Even an activated demo flight control must never reach the backend.
  const land = page.getByRole('button', { name: 'LAND', exact: true })
  await land.hover(); await page.mouse.down(); await page.waitForTimeout(600); await page.mouse.up()
  assert.match(await page.locator('body').innerText(), /SIMULATION — no command sent/i)
  await page.waitForTimeout(3100)
  await page.mouse.move(1278, 899)
  for (let frame = 0; frame < Math.ceil(duration * fps); frame++) {
    await page.evaluate(t => window.dispatchEvent(new CustomEvent('breacheye:demo-time', { detail: t })), frame / fps)
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await page.screenshot({ path: `${output}/${String(frame).padStart(5, '0')}.png` })
    if (frame % 90 === 0) console.log(`Captured ${frame}/${Math.ceil(duration * fps)} frames`)
  }
  assert.deepEqual(errors, [], 'Browser errors')
  assert.deepEqual(hardwareRequests, [], 'Demo must not contact hardware API')
  assert.match(await page.locator('body').innerText(), /APPROACH WALL · SLOW FOR CLEARANCE/)
  console.log('Browser checks passed: layout, scene, timeline, controls, API isolation.')
} finally { await browser.close() }
