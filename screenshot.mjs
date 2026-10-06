// A screenshot of the running portal (:5184) as a signed-in user, without Playwright: drives the
// headless Chromium that Playwright left in ~/.cache over the DevTools protocol (Node 22+ has a
// WebSocket built in), signs in through the real API, plants the token, opens a hash route, waits
// a moment, and writes a PNG. Password is the trial password (1234). Any other user name shows
// the sign-in page itself.
//
//   node screenshot.mjs ag.reviewer / ag-home.png 1440 2400
//   node screenshot.mjs school-education /cases/<id> case.png 1440 2000
//   node screenshot.mjs ag.reviewer / phone.png 390 2000 "All cases"     # click a button/tile first
import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'
const [user, route, out, W = '1440', H = '1400', clickText = ''] = process.argv.slice(2)
const BIN = process.env.HOME + '/.cache/ms-playwright/chromium_headless_shell-1234/chrome-linux/headless_shell'
const port = 9300 + Math.floor(Math.random() * 500)
const chrome = spawn(BIN, ['--headless', '--no-sandbox', '--disable-gpu', '--hide-scrollbars', `--remote-debugging-port=${port}`, `--window-size=${W},${H}`, 'about:blank'], { stdio: 'ignore' })
const sleep = ms => new Promise(r => setTimeout(r, ms))
let wsUrl = null
for (let i = 0; i < 50 && !wsUrl; i++) { try { const j = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); wsUrl = j.find(t => t.type === 'page')?.webSocketDebuggerUrl } catch { await sleep(200) } }
const ws = new WebSocket(wsUrl); await new Promise(r => ws.onopen = r)
let id = 0; const pending = new Map()
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) } }
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
await send('Page.enable'); await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: +W, height: +H, deviceScaleFactor: 1, mobile: +W < 800 })
// A real token from the real API, planted before the app loads.
const login = await (await fetch('http://127.0.0.1:5184/api/v2/auth/login', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ username: user, password: '1234', portal: 'ag' }) })).json()
if (login.token) await send('Page.addScriptToEvaluateOnNewDocument', { source: `sessionStorage.setItem('pension.ag.token', ${JSON.stringify(login.token)})` })
else console.error('login failed', JSON.stringify(login).slice(0, 200))
await send('Page.navigate', { url: `http://127.0.0.1:5184/#${route}` })
await sleep(3500)
if (clickText) {
  await send('Runtime.evaluate', { expression: `(() => { const b = [...document.querySelectorAll('button,a,.tile')].find(x => (x.textContent||'').trim().startsWith(${JSON.stringify(clickText)})); if (b) b.click(); return !!b })()` })
  await sleep(2500)
}
const { result } = await send('Runtime.evaluate', { expression: 'document.title + " | " + document.body.scrollHeight', returnByValue: true })
console.log(result.value)
const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
writeFileSync(out, Buffer.from(shot.result.data, 'base64'))
ws.close(); chrome.kill()
