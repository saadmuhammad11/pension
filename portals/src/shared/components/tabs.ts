/** Keyboard behaviour for a tab strip (frontend review F15): Left/Right (and Home/End) move
 *  between the tabs, as WAI-ARIA asks of a `tablist`; the tab panels name their tab through
 *  `aria-controls`. Returns the tab to select for a key, or null for any other key. */
export function nextTabFor<T>(tabs: readonly T[], current: T, key: string): T | null {
  const i = tabs.indexOf(current)
  if (i < 0 || tabs.length === 0) return null
  switch (key) {
    case 'ArrowRight': return tabs[(i + 1) % tabs.length]
    case 'ArrowLeft': return tabs[(i - 1 + tabs.length) % tabs.length]
    case 'Home': return tabs[0]
    case 'End': return tabs[tabs.length - 1]
    default: return null
  }
}

/** A stable id for a tab and its panel: "case-tab-ai-findings", "case-panel-ai-findings". */
export const tabId = (prefix: string, name: string) => `${prefix}-${String(name).toLowerCase().replace(/[^a-z0-9]+/g, '-')}`
