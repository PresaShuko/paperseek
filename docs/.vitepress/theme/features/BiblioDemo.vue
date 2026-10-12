<script setup lang="ts">
// Bibliometrics: the whole corpus settles into a year chart, then opens as a keyword network.
import { computed, ref } from 'vue'
import { useStage, glide, press, HAND } from './useStage'

const props = defineProps<{ zh: boolean }>()
const t = (en: string, cn: string) => props.zh ? cn : en
const W = 880, H = 540
const frame = ref<HTMLElement>()
const stage = ref<HTMLElement>()

const tabs = [t('Overview', '概览'), t('Keyword topics', '关键词主题'), t('Bibliographic coupling', '文献耦合')]
const stats = [[t('Papers analyzed', '分析文献'), 642, t('Fetched and deduplicated', '本次获取并去重')], [t('Reported citations', '报告被引'), 18240, t('Native counts per source', '按数据源原生计数')], [t('Venues', '期刊与会议'), 214, t('Journals and proceedings', '期刊与会议论文集')]] as const
const years = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
const counts = [12, 19, 31, 44, 63, 88, 131, 162, 92]
const BASE = 470, MAXH = 220, X0 = 74, STEP = 84, COLW = 50
const bars = counts.map((c, i) => ({ x: X0 + i * STEP, h: Math.round(c / 162 * MAXH), c, y: years[i] }))
const dots: { x: number; y: number; row: number; col: number }[] = []
bars.forEach((bar, col) => {
  const rows = Math.max(1, Math.round(bar.h / 12.5))
  for (let row = 0; row < rows; row++) for (let k = 0; k < 4; k++) dots.push({ x: bar.x + 1 + k * 12.5, y: BASE - 11 - row * 12.5, row, col })
})

// Keyword, count and cluster, laid out by hand so labels never collide.
const words: [string, string, number, number, number, number][] = [
  ['systematic review', '系统综述', 148, 0, 440, 330], ['large language models', '大语言模型', 121, 1, 610, 400], ['screening', '文献筛选', 109, 0, 290, 405],
  ['recall', '召回率', 74, 1, 170, 470], ['evidence synthesis', '证据综合', 82, 0, 150, 320], ['automation', '自动化', 66, 1, 270, 250],
  ['reproducibility', '可重复性', 51, 2, 450, 228], ['machine learning', '机器学习', 70, 1, 640, 255], ['active learning', '主动学习', 44, 2, 790, 330],
  ['reporting', '报告规范', 38, 2, 780, 462],
]
const nodes = words.map(([en, cn, count, group, x, y]) => ({ label: t(en, cn), r: 5 + Math.sqrt(count) * 1.15, group, x, y }))
const edges: [number, number][] = [[0, 1], [0, 2], [1, 2], [0, 4], [2, 3], [1, 5], [1, 7], [2, 5], [4, 6], [3, 7], [6, 9], [8, 2], [8, 7], [0, 9], [5, 7]]
const colors = ['var(--d-blue)', 'var(--d-ink)', 'var(--d-teal)']

const steps = [['overview', t('Overview', '概览')], ['keywords', t('Keyword topics', '关键词主题')]] as const

const { scale, progress, seek, labelTime } = useStage(frame, stage, { width: W, height: H }, (gsap, root) => {
  const q = (s: string) => root.querySelector(s)!
  const qa = (s: string) => [...root.querySelectorAll(s)]
  const tl = gsap.timeline({ repeat: -1, repeatDelay: 0.2 })
  tl.set(q('.bd-all'), { opacity: 1 }, 0)
  tl.addLabel('overview', 0)
  // Numbers count up.
  qa('.bd-stat').forEach((s, i) => {
    tl.fromTo(s, { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.4, ease: 'power3.out' }, 0.1 + i * 0.1)
    const n = s.querySelector('.bd-n')!, to = stats[i][1], o = { v: 0 }
    tl.fromTo(o, { v: 0 }, { v: to, duration: 1.4, ease: 'expo.out', onUpdate: () => { n.textContent = Math.round(o.v).toLocaleString('en-US') } }, 0.2 + i * 0.1)
  })
  // Every paper drops into its publication year, then the columns settle into bars.
  qa('.bd-dot').forEach((d, i) => {
    const { row, col } = dots[i]
    tl.fromTo(d, { y: -240, opacity: 0 }, { y: 0, opacity: 1, duration: 0.45, ease: 'power3.in' }, 0.35 + row * 0.05 + col * 0.022 + (i % 4) * 0.008)
  })
  tl.fromTo(qa('.bd-yr'), { opacity: 0 }, { opacity: 1, duration: 0.3, stagger: 0.02 }, 1.2)
  tl.fromTo(qa('.bd-bar'), { scaleY: 0 }, { scaleY: 1, duration: 0.45, ease: 'expo.out', stagger: 0.03 }, 2.0)
  tl.fromTo(q('.bd-dots'), { opacity: 1 }, { opacity: 0, duration: 0.3 }, 2.3)
  tl.fromTo(qa('.bd-val'), { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.3, stagger: 0.03 }, 2.2)
  // Open keyword topics.
  const hand = q('.psd-cursor')
  tl.fromTo(hand, { opacity: 0 }, { opacity: 1, duration: 0.15 }, 3.3)
  glide(tl, hand, [820, 560], [255, 33], 3.3, 0.8)
  press(tl, hand, null, 4.15)
  tl.addLabel('keywords', 4.15)
  tl.fromTo(q('.bd-tab-on'), { x: 0 }, { x: 168, duration: 0.35, ease: 'expo.out' }, 4.2)
  tl.to(hand, { opacity: 0, duration: 0.2 }, 4.7)
  tl.fromTo(q('.bd-chart'), { opacity: 1 }, { opacity: 0, duration: 0.25 }, 4.2)
  tl.fromTo(q('.bd-net'), { opacity: 0 }, { opacity: 1, duration: 0.2 }, 4.3)
  qa('.bd-node').forEach((n, i) => {
    tl.fromTo(n, { x: 440 - nodes[i].x, y: 345 - nodes[i].y, scale: 0, transformOrigin: '50% 50%' }, { x: 0, y: 0, scale: 1, duration: 0.8, ease: 'expo.out' }, 4.35 + i * 0.03)
  })
  qa('.bd-edge').forEach((e, i) => {
    const len = (e as SVGLineElement).getTotalLength?.() || 300
    tl.fromTo(e, { strokeDasharray: len, strokeDashoffset: len }, { strokeDashoffset: 0, duration: 0.5, ease: 'power2.out' }, 4.7 + i * 0.03)
  })
  tl.fromTo(qa('.bd-label'), { opacity: 0 }, { opacity: 1, duration: 0.3, stagger: 0.03 }, 5.0)
  tl.addLabel('end', 5.9)
  tl.to(q('.bd-all'), { opacity: 0, duration: 0.4 }, 8.6)
  return tl
})
const current = computed(() => {
  let index = 0
  steps.forEach(([label], i) => { if (progress.value >= labelTime(label) - 0.01) index = i })
  return index
})
</script>

<template>
  <div class="psd">
    <div class="psd-top"><i /><i /><i /><b>{{ t('Bibliometrics', '文献计量') }}</b><span>/ {{ t('LLM abstract screening', 'LLM 摘要筛选') }}</span><span class="psd-tag">{{ t('ILLUSTRATION', '示意') }}</span></div>
    <div ref="frame" class="psd-frame" :style="{ height: `${H * scale}px` }">
      <div ref="stage" class="psd-stage" :style="{ width: `${W}px`, height: `${H}px`, transform: `scale(${scale})` }" aria-hidden="true">
        <div class="bd-all">
          <div class="bd-tabs"><span class="bd-tab-on" /><span v-for="tab in tabs" :key="tab">{{ tab }}</span></div>
          <div v-for="(s, i) in stats" :key="i" class="bd-stat" :style="{ left: `${24 + i * 282}px` }"><small>{{ s[0] }}</small><div class="bd-n">0</div><em>{{ s[2] }}</em></div>
          <div class="bd-panel" />
          <div class="bd-chart">
            <div class="bd-title"><b>{{ t('Publication years', '发表年份') }}</b> 2017 – 2025</div>
            <div v-for="(bar, i) in bars" :key="i" class="bd-bar" :style="{ left: `${bar.x}px`, top: `${BASE - bar.h}px`, width: `${COLW}px`, height: `${bar.h}px` }" />
            <div v-for="(bar, i) in bars" :key="`v${i}`" class="bd-val" :style="{ left: `${bar.x}px`, top: `${BASE - bar.h - 20}px` }">{{ bar.c }}</div>
            <div v-for="(bar, i) in bars" :key="`y${i}`" class="bd-yr" :style="{ left: `${bar.x}px`, top: `${BASE + 10}px` }">{{ bar.y }}</div>
            <div class="bd-dots"><i v-for="(d, i) in dots" :key="i" class="bd-dot" :style="{ left: `${d.x}px`, top: `${d.y}px` }" /></div>
          </div>
          <div class="bd-net">
            <div class="bd-title"><b>{{ t('Keyword co-occurrence', '关键词共现') }}</b> {{ t('600 papers with keywords', '600 篇含关键词') }}</div>
            <svg viewBox="0 0 880 540" width="880" height="540">
              <line v-for="([a, b], i) in edges" :key="i" class="bd-edge" :x1="nodes[a].x" :y1="nodes[a].y" :x2="nodes[b].x" :y2="nodes[b].y" />
              <g v-for="(n, i) in nodes" :key="i" class="bd-node"><circle :cx="n.x" :cy="n.y" :r="n.r" :fill="colors[n.group]" /></g>
              <text v-for="(n, i) in nodes" :key="`l${i}`" class="bd-label" :x="n.x" :y="n.y + n.r + 15" text-anchor="middle">{{ n.label }}</text>
            </svg>
          </div>
          <div class="psd-cursor" v-html="HAND" />
        </div>
      </div>
    </div>
    <div class="psd-steps" role="group" :aria-label="t('Analysis views', '分析视图')">
      <button v-for="([label, text], i) in steps" :key="label" type="button" :aria-current="current === i ? 'step' : undefined" @click="seek(label)"><b>{{ i + 1 }}</b>{{ text }}</button>
    </div>
  </div>
</template>

<style scoped>
.bd-all { position: absolute; inset: 0; }
.bd-tabs { position: absolute; left: 24px; top: 18px; display: flex; padding: 3px; border-radius: 10px; background: var(--d-soft); }
.bd-tabs > span:not(.bd-tab-on) { position: relative; width: 168px; text-align: center; white-space: nowrap; line-height: 24px; font-size: 12.5px; font-weight: 500; }
.bd-tab-on { position: absolute; left: 3px; top: 3px; width: 168px; height: 24px; border-radius: 8px; background: var(--d-bg); box-shadow: 0 1px 2px rgb(0 0 0 / .08); }
.bd-stat { position: absolute; top: 64px; width: 268px; height: 82px; border: 1px solid var(--d-border); border-radius: 12px; padding: 12px 16px; background: var(--d-bg); }
.bd-stat small { display: block; font-size: 11.5px; color: var(--d-muted); }
.bd-n { font-size: 26px; font-weight: 650; letter-spacing: -.03em; font-variant-numeric: tabular-nums; line-height: 1.2; margin-top: 2px; }
.bd-stat em { font-style: normal; font-size: 10.5px; color: var(--d-muted); }
.bd-panel { position: absolute; left: 24px; top: 162px; width: 832px; height: 356px; border: 1px solid var(--d-border); border-radius: 12px; }
.bd-chart, .bd-net { position: absolute; inset: 0; }
.bd-net { opacity: 0; }
.bd-title { position: absolute; left: 42px; top: 178px; font-size: 12px; color: var(--d-muted); }
.bd-title b { color: var(--d-fg); font-size: 13.5px; font-weight: 600; margin-right: 8px; }
.bd-bar { position: absolute; background: var(--d-blue); border-radius: 6px 6px 2px 2px; transform-origin: 50% 100%; }
.bd-val, .bd-yr { position: absolute; width: 50px; text-align: center; font-family: var(--vp-font-family-mono); font-size: 11px; color: var(--d-muted); }
.bd-dots { position: absolute; inset: 0; }
.bd-dot { position: absolute; width: 10px; height: 10px; border-radius: 50%; background: var(--d-ink); }
.bd-net svg { position: absolute; left: 0; top: 0; overflow: visible; }
.bd-edge { stroke: var(--d-muted); stroke-opacity: .35; stroke-width: 1.4; }
.bd-label { font-size: 12px; fill: var(--d-fg); }
</style>
