// Wheel and trackpad move the home page one section at a time on large screens.
// CSS scroll snapping (features.css) still aligns keyboard, scrollbar and resize scrolling; this handles the wheel,
// which CSS alone snaps to the nearest page and would send a short scroll back where it started.
const LARGE = '(min-width: 960px) and (min-height: 640px)'
const SECTIONS = '.ps-hero, .ps-feature, .ps-choice-section, .ps-resources'
// A gesture has to travel this far before it turns the page. Trackpads (macOS especially) send stray 1–3 px
// events from resting fingers and from the end of momentum; those must never move a whole section.
const INTENT = 24
// Wheel events closer together than this belong to the same gesture, including trackpad momentum.
const QUIET_MS = 350

export function pageSnap(): () => void {
  const large = window.matchMedia(LARGE)
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
  let lastWheel = 0
  let travel = 0
  let lockedUntil = 0

  const navHeight = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--vp-nav-height')) || 64
  const stops = () => {
    const max = document.documentElement.scrollHeight - window.innerHeight
    const tops = [...document.querySelectorAll<HTMLElement>(SECTIONS)]
      .map((el) => Math.min(max, Math.round(el.getBoundingClientRect().top + window.scrollY - navHeight())))
    return [...new Set([...tops, max])].sort((a, b) => a - b)
  }
  const pixels = (event: WheelEvent) =>
    event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? window.innerHeight : 1)

  function onWheel(event: WheelEvent) {
    if (!large.matches || event.ctrlKey || Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return
    const now = performance.now()
    const gap = now - lastWheel
    lastWheel = now
    // After a move, the rest of that gesture (and its momentum) is swallowed until the wheel goes quiet.
    if (now < lockedUntil) { lockedUntil = now + QUIET_MS; event.preventDefault(); return }
    if (gap > QUIET_MS) travel = 0
    const delta = pixels(event)
    // A reversal starts a new intent.
    if (travel && Math.sign(delta) !== Math.sign(travel)) travel = 0
    travel += delta

    const y = window.scrollY
    const down = travel > 0
    const points = stops()
    const page = window.innerHeight - navHeight()
    const next = points.find((p) => p > y + 2)
    const previous = [...points].reverse().find((p) => p < y - 2)
    // Inside a section taller than the screen, scroll normally until its edge comes into view.
    if (down && next !== undefined && next - y > page + 4) return
    const current = [...points].reverse().find((p) => p <= y + 2) ?? 0
    if (!down && y - current > 2) return
    const target = down ? next : previous
    if (target === undefined) return
    // Below the intent threshold, hold the page still; CSS snapping keeps it aligned.
    event.preventDefault()
    if (Math.abs(travel) < INTENT) return

    travel = 0
    lockedUntil = now + Math.max(QUIET_MS, 700)
    window.scrollTo({ top: target, behavior: reduced.matches ? 'auto' : 'smooth' })
  }

  window.addEventListener('wheel', onWheel, { passive: false })
  return () => window.removeEventListener('wheel', onWheel)
}
