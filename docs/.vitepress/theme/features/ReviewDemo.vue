<script setup lang="ts">
// Literature review: evidence from abstracts → an outline you confirm → a cited draft → trace a citation to its source.
import { computed, ref } from 'vue'
import { useStage, glide, press, shimmer, HAND } from './useStage'

const props = defineProps<{ zh: boolean }>()
const t = (en: string, cn: string) => props.zh ? cn : en
const W = 880, H = 540
const frame = ref<HTMLElement>()
const stage = ref<HTMLElement>()

const papers = [
  { title: 'Large language models for title and abstract screening: a comparative evaluation', au: 'Lin A, Reyes M · 2024', pre: 'Recall, workload saved and ', quote: 'agreement with two human reviewers', post: ' across twelve systematic reviews.' },
  { title: 'Prompt design and calibration for automated citation screening', au: 'Okafor A, Reyes M · 2023', pre: 'How instructions, examples and a held-out calibration set ', quote: 'change sensitivity and specificity', post: '.' },
  { title: 'Workload reduction in systematic reviews with machine-assisted screening', au: 'Müller A, Reyes M · 2024', pre: 'A prospective study of ', quote: 'reviewer time and missed studies', post: ' when a model ranks abstracts first.' },
  { title: 'Reproducibility of model-based eligibility decisions', au: 'Silva A, Reyes M · 2022', pre: 'Repeated runs, ', quote: 'model updates and their effect', post: ' on which studies are included.' },
]
const sections = [
  [t('Screening performance', '筛选表现'), t('Compare recall with human reviewers.', '比较模型与人工评审的召回率。'), [0, 1]],
  [t('Workload and reproducibility', '工作量与可重复性'), t('Time saved, and how stable model decisions are.', '节省的时间，以及模型判断是否稳定。'), [2, 3]],
] as const
// Draft text: pieces of prose, each optionally followed by a numbered citation.
const draft = computed(() => props.zh
  ? [[['在十二项系统综述中，LLM 筛选的召回率与第二位人工评审者相当', 1], ['；经过校准的提示词以少量特异性换取更少的漏检', 2], ['。', 0]],
     [['先由模型对摘要排序，可在不减少纳入研究的前提下节省评审时间', 3], ['，但模型更新会改变纳入判断，应记录模型版本与提示词', 4], ['。', 0]]]
  : [[['Across twelve reviews, LLM screening reached recall comparable to a second human reviewer', 1], [', while calibrated prompts traded a little specificity for fewer missed studies', 2], ['.', 0]],
     [['Ranking abstracts first cut reviewer time without lowering the number of included studies', 3], [', but model updates can change eligibility decisions, so record model versions and prompts', 4], ['.', 0]]])
const pieces = (text: string) => props.zh ? text.match(/.{1,2}/gu) ?? [] : text.split(/(?<= )/)
const statuses = [
  [t('Extracting evidence…', '正在提取摘要证据…'), 0.2, 2.5], [t('Evidence cards ready', '已整理证据'), 2.6, 3.35],
  [t('Building the outline…', '正在生成大纲…'), 3.45, 4.9], [t('Outline ready · 2 sections', '大纲已就绪 · 2 节'), 5.0, 6.3],
  [t('Writing the draft…', '正在撰写正文…'), 6.45, 9.9], [t('Evidence checked', '已检查证据'), 10.0, null],
] as const
const steps = [['evidence', t('Evidence', '证据')], ['outline', t('Outline', '大纲')], ['draft', t('Draft', '正文')], ['trace', t('Trace', '溯源')]] as const
const SLOT = { left: 150, top: 110, gap: 130 }

const { scale, progress, seek, labelTime } = useStage(frame, stage, { width: W, height: H }, (gsap, root) => {
  const q = (s: string) => root.querySelector(s)!
  const qa = (s: string) => [...root.querySelectorAll(s)]
  const tl = gsap.timeline({ repeat: -1, repeatDelay: 0.2 })
  tl.set(q('.rd-all'), { opacity: 1 }, 0)
  tl.addLabel('evidence', 0)
  tl.fromTo(q('.rd-status'), { opacity: 0, y: -10 }, { opacity: 1, y: 0, duration: 0.35 }, 0.05)
  tl.fromTo(q('.rd-status .psd-spin'), { rotation: 0 }, { rotation: 1800, duration: 10, ease: 'none' }, 0)
  qa('.rd-status .psd-sw').forEach((w, i) => {
    const [, a, b] = statuses[i]
    tl.fromTo(w, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.25 }, a)
    if (/…$/.test(statuses[i][0])) shimmer(tl, [...w.querySelectorAll('span')], a + 0.15, Math.max(1, Math.floor((b! - a) / 1.1)))
    if (b != null) tl.to(w, { opacity: 0, y: -8, duration: 0.2 }, b)
  })

  // 1 · Evidence quoted from each abstract.
  const cards = qa('.rd-abs')
  cards.forEach((c, i) => tl.fromTo(c, { opacity: 0, y: 70, rotation: (i % 2 ? 2 : -2) }, { opacity: 1, y: 0, rotation: 0, duration: 0.7, ease: 'expo.out' }, 0.1 + i * 0.08))
  ;[0.9, 1.3, 1.65, 1.95].forEach((at, i) => {
    tl.fromTo(cards[i].querySelector('.psd-mark'), { backgroundSize: '0% 100%' }, { backgroundSize: '100% 100%', duration: 0.35, ease: 'power2.inOut' }, at)
    tl.fromTo(cards[i].querySelector('.rd-ev'), { opacity: 0, scale: 0.5 }, { opacity: 1, scale: 1, duration: 0.3, ease: 'back.out(3)' }, at + 0.25)
  })

  // 2 · Papers move into the outline you confirm.
  tl.addLabel('outline', 3.3)
  cards.forEach((c, i) => tl.to(c, { scale: 0.3, opacity: 0, duration: 0.35, ease: 'power2.in' }, 3.3 + i * 0.03))
  qa('.rd-row').forEach((r, i) => tl.fromTo(r, { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.45, ease: 'expo.out' }, 3.5 + i * 0.1))
  let at = 3.9
  qa('.rd-chip').forEach((chip) => {
    const el = chip as HTMLElement
    const sx = +el.dataset.sx!, sy = +el.dataset.sy!, tx = +el.dataset.tx!, ty = +el.dataset.ty!
    tl.fromTo(el, { x: sx - tx, y: sy - ty, scale: 0, opacity: 1 }, { scale: 1, duration: 0.25, ease: 'back.out(2)' }, 3.35)
    tl.fromTo(el, { x: sx - tx, y: sy - ty }, { x: 0, y: 0, duration: 0.7, ease: 'expo.inOut', immediateRender: false }, at)
    at += 0.12
  })
  const go = q('.rd-go')
  tl.fromTo(go, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.3 }, 4.8)
  const hand = q('.psd-cursor')
  tl.fromTo(hand, { opacity: 0 }, { opacity: 1, duration: 0.15 }, 5.0)
  const gx = (go as HTMLElement).offsetLeft + (go as HTMLElement).offsetWidth / 2, gy = (go as HTMLElement).offsetTop + 19
  glide(tl, hand, [840, 560], [gx, gy], 5.0, 0.75)
  press(tl, hand, go, 5.85)
  tl.to(hand, { opacity: 0, duration: 0.15 }, 6.2)

  // 3 · The draft is written with citations.
  tl.to(q('.rd-outline'), { opacity: 0, y: -14, duration: 0.3, ease: 'power2.in' }, 6.15)
  tl.addLabel('draft', 6.4)
  tl.fromTo(q('.rd-doc'), { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.5, ease: 'expo.out' }, 6.4)
  let w = 6.7
  qa('.rd-sec').forEach((sec, si) => {
    tl.fromTo(sec.querySelector('.rd-h'), { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.3 }, w - 0.15)
    sec.querySelectorAll('.rd-p > span').forEach((s) => {
      if (s.classList.contains('psd-cite')) {
        tl.fromTo(s, { opacity: 0, scale: 0.3 }, { opacity: 1, scale: 1, duration: 0.3, ease: 'back.out(3)' }, w)
        tl.fromTo(s.querySelector('.on'), { opacity: 1 }, { opacity: 0, duration: 0.5 }, w + 0.3)
        w += 0.1
      } else { tl.fromTo(s, { opacity: 0 }, { opacity: 1, duration: 0.12 }, w); w += props.zh ? 0.05 : 0.04 }
    })
    tl.fromTo(sec.querySelector('.rd-ok'), { opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1, duration: 0.3, ease: 'back.out(3)' }, w + 0.05)
    tl.fromTo(q('.rd-prog'), { textContent: si }, { textContent: si + 1, duration: 0.01, snap: { textContent: 1 } }, w + 0.05)
    w += 0.35
  })

  // 4 · Trace a citation back to the sentence it came from.
  const T = Math.max(w + 0.2, 10.3)
  tl.addLabel('trace', T)
  const chip = q('.rd-sec .psd-cite') as HTMLElement
  let cx = 0, cy = 0
  for (let e: HTMLElement | null = chip; e && e !== root; e = e.offsetParent as HTMLElement | null) { cx += e.offsetLeft; cy += e.offsetTop }
  cx += chip.offsetWidth / 2; cy += chip.offsetHeight / 2
  tl.fromTo(hand, { opacity: 0 }, { opacity: 1, duration: 0.15 }, T - 0.2)
  glide(tl, hand, [840, 560], [cx, cy], T - 0.2, 0.7)
  tl.to(chip.querySelector('.on'), { opacity: 1, duration: 0.2 }, T + 0.55)
  const path = q('.rd-link path') as SVGPathElement
  path.setAttribute('d', `M${cx} ${cy + 10} C ${cx} ${cy + 90}, 470 ${cy + 40}, 470 316`)
  const ends = qa('.rd-link circle')
  ends[0].setAttribute('cx', String(cx)); ends[0].setAttribute('cy', String(cy + 10))
  const len = path.getTotalLength()
  tl.fromTo(path, { strokeDasharray: len, strokeDashoffset: len }, { strokeDashoffset: 0, duration: 0.45, ease: 'power2.inOut' }, T + 0.65)
  tl.fromTo(ends, { opacity: 0 }, { opacity: 1, duration: 0.1, stagger: 0.4 }, T + 0.65)
  tl.fromTo(q('.rd-src'), { opacity: 0, x: 24 }, { opacity: 1, x: 0, duration: 0.45, ease: 'expo.out' }, T + 1.0)
  tl.fromTo(q('.rd-src .psd-mark'), { backgroundSize: '0% 100%' }, { backgroundSize: '100% 100%', duration: 0.6, ease: 'power2.inOut' }, T + 1.4)
  tl.to(hand, { opacity: 0, duration: 0.2 }, T + 1.5)
  tl.addLabel('end', T + 2.1)
  tl.to(q('.rd-all'), { opacity: 0, duration: 0.4 }, T + 4.6)
  return tl
})

const current = computed(() => {
  const now = progress.value
  let index = 0
  steps.forEach(([label], i) => { if (now >= labelTime(label) - 0.01) index = i })
  return index
})

// Where each paper chip starts (the centre of its abstract card) and lands (its outline slot).
const chips = computed(() => sections.flatMap(([, , ps], si) => ps.map((pi, j) => ({
  n: pi + 1,
  sx: 40 + (pi % 2) * 410 + 195 - 22, sy: 86 + Math.floor(pi / 2) * 196 + 85 - 12,
  tx: SLOT.left + 58 + j * 52, ty: SLOT.top + si * SLOT.gap + 104 - 16 - 24,
}))))
</script>

<template>
  <div class="psd">
    <div class="psd-top"><i /><i /><i /><b>{{ t('Reviews', '综述') }}</b><span>/ {{ t('LLM-assisted abstract screening', 'LLM 辅助摘要筛选') }}</span><span class="psd-tag">{{ t('ILLUSTRATION', '示意') }}</span></div>
    <div ref="frame" class="psd-frame" :style="{ height: `${H * scale}px` }">
      <div ref="stage" class="psd-stage" :style="{ width: `${W}px`, height: `${H}px`, transform: `scale(${scale})` }" aria-hidden="true">
        <div class="rd-all">
          <div class="rd-status"><span class="psd-spin"><i v-for="k in 12" :key="k" :style="{ transform: `rotate(${k * 30}deg)`, opacity: 0.25 + k / 16 }" /></span><span class="rd-sl"><span v-for="(s, i) in statuses" :key="i" class="psd-sw"><span v-for="(c, k) in [...s[0]]" :key="k">{{ c }}</span></span></span></div>

          <div v-for="(p, i) in papers" :key="i" class="rd-abs" :style="{ left: `${40 + (i % 2) * 410}px`, top: `${86 + Math.floor(i / 2) * 196}px` }">
            <span class="rd-ev">{{ t('Evidence', '证据') }} ✓</span><h6>{{ p.title }}</h6><div class="rd-au">{{ p.au }}</div>
            <p>{{ p.pre }}<span class="psd-mark">{{ p.quote }}</span>{{ p.post }}</p>
          </div>

          <div class="rd-outline">
            <div v-for="(s, i) in sections" :key="i" class="rd-row" :style="{ left: `${SLOT.left}px`, top: `${SLOT.top + i * SLOT.gap}px` }">
              <span class="rd-n">0{{ i + 1 }}</span><h6>{{ s[0] }}</h6><div class="rd-g">{{ s[1] }}</div>
              <div class="rd-slots"><span v-for="k in s[2].length" :key="k" /></div>
            </div>
            <span v-for="c in chips" :key="c.n" class="rd-chip" :data-sx="c.sx" :data-sy="c.sy" :data-tx="c.tx" :data-ty="c.ty" :style="{ left: `${c.tx}px`, top: `${c.ty}px` }">p{{ c.n }}</span>
            <span class="psd-btn rd-go">{{ t('Confirm outline and write', '确认大纲并执行') }}</span>
          </div>

          <div class="rd-doc">
            <div class="rd-bar"><span>{{ t('Papers', '文献') }} 4</span><span>{{ t('Outline', '大纲') }}</span><span class="on">{{ t('Draft', '正文') }}</span><span>{{ t('Evidence', '证据') }}</span></div>
            <div class="rd-progress"><i /><span class="rd-prog">0</span> / 2 {{ t('sections written', '节已完成') }}</div>
            <div v-for="(para, si) in draft" :key="si" class="rd-sec">
              <div class="rd-h">{{ sections[si][0] }}<span class="rd-ok"><i />{{ t('Evidence checked', '已检查证据') }}</span></div>
              <p class="rd-p"><template v-for="([text, n], k) in para" :key="k"><span v-for="(w, j) in pieces(text as string)" :key="`${k}-${j}`">{{ w }}</span><span v-if="n" class="psd-cite">{{ n }}<span class="on">{{ n }}</span></span></template></p>
            </div>
          </div>
          <svg class="rd-link" viewBox="0 0 880 540"><path fill="none" stroke="#3bb8c3" stroke-width="2.4" /><circle r="5" fill="var(--d-bg)" stroke="#3bb8c3" stroke-width="2.4" /><circle cx="470" cy="316" r="5" fill="var(--d-bg)" stroke="#3bb8c3" stroke-width="2.4" /></svg>
          <div class="rd-src">
            <div class="rd-k"><i />{{ t('Source abstract', '来源摘要') }} · p1 · {{ papers[0].au }}</div>
            <h6>{{ papers[0].title }}</h6>
            <p>“{{ papers[0].pre }}<span class="psd-mark">{{ papers[0].quote }}</span>{{ papers[0].post }}”</p>
          </div>
          <div class="psd-cursor" v-html="HAND" />
        </div>
      </div>
    </div>
    <div class="psd-steps" role="group" :aria-label="t('Review steps', '综述步骤')">
      <button v-for="([label, text], i) in steps" :key="label" type="button" :aria-current="current === i ? 'step' : undefined" @click="seek(label)"><b>{{ i + 1 }}</b>{{ text }}</button>
    </div>
  </div>
</template>

<style scoped>
.rd-all { position: absolute; inset: 0; }
.rd-status { position: absolute; left: 250px; top: 22px; width: 380px; height: 40px; border-radius: 20px; background: var(--d-soft); display: flex; align-items: center; gap: 12px; padding: 0 16px; font-size: 13px; opacity: 0; }
.rd-sl { position: relative; flex: 1; height: 20px; }
.rd-sl .psd-sw { left: 0; right: auto; }
.rd-abs { position: absolute; width: 390px; height: 176px; border: 1px solid var(--d-border); border-radius: 14px; background: var(--d-bg); padding: 16px 18px; box-shadow: 0 10px 30px rgb(0 0 0 / .05); }
.rd-abs h6 { margin: 0; font-size: 13.5px; font-weight: 600; line-height: 1.35; height: 37px; overflow: hidden; }
.rd-au { font-size: 11px; color: var(--d-muted); margin-top: 4px; }
.rd-abs p { margin: 10px 0 0; font-size: 13px; line-height: 1.55; color: var(--d-muted); }
.rd-abs .psd-mark { color: var(--d-fg); }
.rd-ev { position: absolute; right: 14px; top: -11px; background: var(--d-ink); color: var(--d-inv); font-size: 11px; font-weight: 600; border-radius: 999px; padding: 2px 9px; opacity: 0; }
.rd-outline { position: absolute; inset: 0; }
.rd-row { position: absolute; width: 580px; height: 104px; border: 1px solid var(--d-border); border-radius: 14px; background: var(--d-bg); padding: 14px 18px 0 58px; opacity: 0; }
.rd-n { position: absolute; left: 20px; top: 16px; font-family: var(--vp-font-family-mono); font-size: 12px; color: var(--d-muted); }
.rd-row h6 { margin: 0; font-size: 16px; font-weight: 600; }
.rd-g { font-size: 12px; color: var(--d-muted); margin-top: 3px; }
.rd-slots { position: absolute; left: 58px; bottom: 16px; display: flex; gap: 8px; }
.rd-slots span { width: 44px; height: 24px; border: 1.5px dashed var(--d-border); border-radius: 7px; }
.rd-chip { position: absolute; width: 44px; height: 24px; border-radius: 7px; background: var(--d-ink); color: var(--d-inv); font-family: var(--vp-font-family-mono); font-size: 12px; display: flex; align-items: center; justify-content: center; opacity: 0; }
.rd-go { position: absolute; right: 150px; top: 386px; height: 38px; padding: 0 18px; font-size: 13px; opacity: 0; }
.rd-doc { position: absolute; left: 40px; top: 80px; width: 800px; height: 440px; border: 1px solid var(--d-border); border-radius: 14px; background: var(--d-bg); padding: 16px 0 0; opacity: 0; box-shadow: 0 14px 40px rgb(0 0 0 / .05); }
.rd-bar { display: inline-flex; margin-left: 18px; padding: 3px; border-radius: 9px; background: var(--d-soft); font-size: 12px; font-weight: 500; }
.rd-bar span { padding: 0 10px; line-height: 22px; border-radius: 7px; }
.rd-bar .on { background: var(--d-bg); box-shadow: 0 1px 2px rgb(0 0 0 / .08); }
.rd-progress { position: absolute; right: 22px; top: 20px; font-size: 12px; color: var(--d-muted); display: flex; align-items: center; gap: 6px; }
.rd-progress i, .rd-ok i, .rd-k i { width: 8px; height: 8px; border-radius: 50%; background: #16a34a; display: inline-block; }
.rd-sec { margin: 22px 44px 0 54px; }
.rd-h { display: flex; align-items: center; gap: 12px; font-size: 18px; font-weight: 650; letter-spacing: -.01em; }
.rd-ok { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 500; color: var(--d-muted); border: 1px solid var(--d-border); border-radius: 999px; padding: 1px 9px; }
.rd-p { margin: 10px 0 0; font-size: 15px; line-height: 1.75; }
.rd-link { position: absolute; left: 0; top: 0; width: 880px; height: 540px; overflow: visible; pointer-events: none; }
.rd-link path { stroke-dasharray: 2000; stroke-dashoffset: 2000; }
.rd-link circle { opacity: 0; }
.rd-src { position: absolute; left: 470px; top: 300px; width: 380px; border: 1px solid var(--d-border); border-radius: 14px; background: var(--d-bg); padding: 14px 18px; box-shadow: 0 20px 50px rgb(0 0 0 / .14); opacity: 0; }
.rd-k { font-size: 11px; color: var(--d-muted); display: flex; align-items: center; gap: 6px; }
.rd-src h6 { margin: 6px 0 0; font-size: 13.5px; font-weight: 600; line-height: 1.35; }
.rd-src p { margin: 8px 0 0; font-size: 13px; line-height: 1.55; color: var(--d-muted); }
.rd-src .psd-mark { color: var(--d-fg); }
</style>
