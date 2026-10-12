// A fixed-size animated stage that scales to its container, plays only while visible,
// and shows its finished state when the reader prefers reduced motion.
import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'
import type { gsap as GSAP } from 'gsap'

export type Timeline = ReturnType<typeof GSAP.timeline>

export function useStage(
  frame: Ref<HTMLElement | undefined>,
  stage: Ref<HTMLElement | undefined>,
  size: { width: number; height: number },
  build: (gsap: typeof GSAP, root: HTMLElement) => Timeline,
) {
  const scale = ref(1)
  const progress = ref(0)
  let timeline: Timeline | undefined
  let resize: ResizeObserver | undefined
  let visible: IntersectionObserver | undefined
  let reduced = false

  onMounted(async () => {
    if (!frame.value || !stage.value) return
    resize = new ResizeObserver(([entry]) => { scale.value = entry.contentRect.width / size.width })
    resize.observe(frame.value)
    const { gsap } = await import('gsap')
    if (!stage.value) return
    timeline = build(gsap, stage.value)
    timeline.eventCallback('onUpdate', () => { progress.value = timeline!.time() })
    reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      timeline.seek(timeline.labels.end ?? timeline.duration(), false).pause()
      return
    }
    timeline.pause(0)
    visible = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) timeline?.play()
      else timeline?.pause()
    }, { threshold: 0.35 })
    visible.observe(frame.value)
  })

  onBeforeUnmount(() => {
    resize?.disconnect()
    visible?.disconnect()
    timeline?.kill()
  })

  // Jump to a labelled moment (used by step buttons); keeps playing unless motion is reduced.
  function seek(label: string) {
    if (!timeline) return
    timeline.seek(label, false)
    if (!reduced) timeline.play()
  }

  return { scale, progress, seek, labelTime: (label: string) => timeline?.labels[label] ?? 0 }
}

// The cursor used across the demos; its fingertip sits at (11, 3) of the 32-unit drawing.
export const HAND = '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M11 3.5c1.1 0 2 .9 2 2V14l.6-.1V11c0-1.1.9-2 2-2s2 .9 2 2v3l.5.1V12c0-1.1.9-2 2-2s2 .9 2 2v3.2l.5.1V14c0-1.1.9-2 2-2s2 .9 2 2v7c0 4.7-3.6 8.5-8.5 8.5h-1.3c-2.6 0-4.6-1-6.2-3l-5-6.3c-.7-.9-.6-2.2.3-2.9.9-.7 2.1-.6 2.9.2L9 19.4V5.5c0-1.1.9-2 2-2z" fill="#fff" stroke="#000" stroke-width="1.5" stroke-linejoin="round"/><path d="M13 14v5M17.6 14v5M22.1 15.3V19" stroke="#000" stroke-width="1.3" stroke-linecap="round"/></svg>'

// Glide a cursor of `size` units so its fingertip travels from a to b along a gentle curve.
export function glide(tl: Timeline, cursor: Element, a: [number, number], b: [number, number], at: number, duration = 0.8, size = 48) {
  const hx = size * 11 / 32, hy = size * 3.5 / 32
  tl.fromTo(cursor, { x: a[0] - hx }, { x: b[0] - hx, duration, ease: 'power2.inOut', immediateRender: false }, at)
  tl.fromTo(cursor, { y: a[1] - hy }, { y: b[1] - hy, duration, ease: 'power3.out', immediateRender: false }, at)
}

export function press(tl: Timeline, cursor: Element, target: Element | null, at: number) {
  tl.to(cursor, { scale: 0.86, duration: 0.07 }, at)
  tl.to(cursor, { scale: 1, duration: 0.25, ease: 'back.out(3)' }, at + 0.08)
  if (target) {
    tl.to(target, { scale: 0.94, duration: 0.07 }, at)
    tl.to(target, { scale: 1, duration: 0.3, ease: 'back.out(3)' }, at + 0.08)
  }
}

// Reveal pre-rendered characters (each a <span>) one by one.
export function type(tl: Timeline, chars: Element[], at: number, step = 0.04) {
  chars.forEach((c, i) => tl.set(c, { display: 'inline' }, at + i * step))
  return at + chars.length * step
}

// A dimming wave through the letters of a status word.
export function shimmer(tl: Timeline, letters: Element[], at: number, passes = 1) {
  for (let p = 0; p < passes; p++)
    letters.forEach((l, i) => tl.to(l, { opacity: 0.25, duration: 0.13, yoyo: true, repeat: 1, ease: 'sine.inOut' }, at + p * 1.1 + i * 0.02))
}
