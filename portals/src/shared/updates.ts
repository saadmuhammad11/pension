/** A tab keeps the build it loaded; the office leaves tabs open for days. Every minute, and
 *  whenever the tab comes back into view, this asks the server for the page and compares the
 *  bundle it names with the one running here. A newer build reloads the tab -- when nothing is
 *  being typed, so a half-written remark is not lost. (29 Sep 2026: two officers saw screens
 *  from a build that had already been replaced.) */
const running = [...document.scripts].map(s => s.src).find(s => /\/assets\/index-[^/]+\.js$/.test(s))?.split('/assets/')[1]

async function check() {
  if (!running || document.visibilityState !== 'visible') return
  try {
    const html = await (await fetch(window.location.pathname || '/', { cache: 'no-store' })).text()
    const served = html.match(/assets\/(index-[^"'/]+\.js)/)?.[1]
    if (!served || served === running) return
    const typing = document.activeElement instanceof HTMLInputElement || document.activeElement instanceof HTMLTextAreaElement
    // Nor while an analysis is being watched (30 Sep 2026): a reload mid-scan looked like the
    // analysis restarting. It waits until the scan has finished.
    const watching = !!document.querySelector('[data-live-analysis]')
    if (typing || watching) { setTimeout(check, 15000); return }
    window.location.reload()
  } catch { /* offline; try again later */ }
}

setInterval(check, 60000)
document.addEventListener('visibilitychange', check)
