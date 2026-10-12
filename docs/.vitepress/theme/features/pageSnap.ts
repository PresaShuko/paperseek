// Wheel and trackpad move the home page one section at a time on large screens.
// CSS scroll snapping (features.css) still aligns keyboard, scrollbar and resize scrolling; this handles the wheel,
// which CSS alone snaps to the nearest page and would send a short scroll back where it started.
const LARGE = '(min-width: 960px) and (min-height: 640px)'
const SECTIONS = '.ps-hero, .ps-feature, .ps-choice-section, .ps-resources'

export function pageSnap(): () => void {
  const large = window.matchMedia(LARGE)
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
  let moving = false
  let armed = true
  let lastWheel = 0

  const navHeight = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--vp-nav-height')) || 64
  const stops = () => {
    const max = document.documentElement.scrollHeight - window.innerHeight
    const tops = [...document.querySelectorAll<HTMLElement>(SECTIONS)]
      .map((el) => Math.min(max, Math.round(el.getBoundingClientRect().top + window.scrollY - navHeight())))
    return [...new Set([...tops, max])].sort((a, b) => a - b)
  }

  function onWheel(event: WheelEvent) {
    if (!large.matches || event.ctrlKey || Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return
    const now = performance.now()
    const gap = now - lastWheel
    lastWheel = now
    // One gesture moves one page: ignore the rest of a move and its trackpad momentum.
    if (moving || (!armed && gap < 180)) { event.preventDefault(); return }
    armed = true

    const y = window.scrollY
    const down = event.deltaY > 0
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

    event.preventDefault()
    moving = true
    armed = false
    window.scrollTo({ top: target, behavior: reduced.matches ? 'auto' : 'smooth' })
    const done = () => { moving = false; window.removeEventListener('scrollend', done) }
    window.addEventListener('scrollend', done)
    window.setTimeout(done, 1000)
  }

  window.addEventListener('wheel', onWheel, { passive: false })
  return () => window.removeEventListener('wheel', onWheel)
}
