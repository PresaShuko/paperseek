<script setup lang="ts">
// Literature search: ask → the four stages run → ranked papers with their reasons.
import { ref } from 'vue'
import { useStage, glide, press, type, shimmer, HAND } from './useStage'

const props = defineProps<{ zh: boolean }>()
const t = (en: string, cn: string) => props.zh ? cn : en
const W = 880, H = 540
const frame = ref<HTMLElement>()
const stage = ref<HTMLElement>()

const question = t('How accurately do LLMs screen abstracts for systematic reviews?', '大语言模型筛选系统综述摘要的准确度如何？')
const statuses = [t('Planning queries…', '正在规划检索式…'), t('Searching OpenAlex…', '正在检索 OpenAlex…'), t('Following citations…', '正在沿引用扩展…'), t('Ranking 120 papers…', '正在为 120 篇文献排序…')]
const stages = [
  [t('Intent and queries', '检索意图与检索式'), t('Compare LLM screening with human reviewers · 3 queries', '比较 LLM 与人工筛选 · 3 条检索式')],
  [t('Query iterations', '检索迭代'), t('2 iterations · 1,284 papers retrieved', '2 轮迭代 · 召回 1,284 篇')],
  [t('Recall and ranking', '候选召回与排序'), t('Citations expanded · 120 sent to the model', '已沿引用扩展 · 120 篇交给模型评分')],
  [t('Results', '文献结果'), t('6 papers worth reading first', '6 篇值得优先阅读')],
]
const papers = [
  { title: 'Large language models for title and abstract screening: a comparative evaluation', meta: 'Lin A, Reyes M · Research Synthesis Methods · 2024', why: t('Directly measures screening recall against human reviewers.', '直接比较了模型与人工评审的筛选召回率。'), score: 9, cites: 148 },
  { title: 'Prompt design and calibration for automated citation screening', meta: 'Okafor A, Reyes M · Research Synthesis Methods · 2023', why: t('Shows how prompt choices shift sensitivity and specificity.', '说明了提示词设计如何影响敏感度与特异度。'), score: 9, cites: 96 },
  { title: 'Workload reduction in systematic reviews with machine-assisted screening', meta: 'Müller A, Reyes M · Research Synthesis Methods · 2024', why: t('Quantifies reviewer time saved in a prospective setting.', '在前瞻性研究中量化了节省的评审时间。'), score: 8, cites: 71 },
]

const { scale } = useStage(frame, stage, { width: W, height: H }, (gsap, root) => {
  const q = (s: string) => root.querySelector(s)!
  const qa = (s: string) => [...root.querySelectorAll(s)]
  const tl = gsap.timeline({ repeat: -1, repeatDelay: 0.2 })
  tl.set(q('.sd-all'), { opacity: 1 }, 0)

  // A dot opens into the question card.
  const card = q('.sd-card')
  tl.fromTo(card, { width: 14, height: 14, borderRadius: 7, scale: 0 }, { scale: 1, duration: 0.4, ease: 'back.out(2.4)' }, 0.1)
  tl.fromTo(q('.sd-teal'), { opacity: 1 }, { opacity: 0, duration: 0.35 }, 0.75)
  tl.to(card, { width: 600, height: 290, borderRadius: 16, duration: 0.7, ease: 'expo.out' }, 0.6)
  tl.fromTo(q('.sd-body'), { opacity: 0 }, { opacity: 1, duration: 0.3 }, 1.0)
  tl.set(q('.sd-ph'), { opacity: 1 }, 0)
  tl.set(q('.sd-ph'), { opacity: 0 }, 1.4)
  const chars = qa('.sd-q span')
  const typed = type(tl, chars, 1.4, 2.2 / chars.length)
  tl.fromTo(q('.sd-caret'), { opacity: 1 }, { opacity: 0, duration: 0.01, repeat: 3, yoyo: true, repeatDelay: 0.2 }, typed)

  // Start search.
  const hand = q('.psd-cursor')
  tl.fromTo(hand, { opacity: 0 }, { opacity: 1, duration: 0.15 }, typed + 0.1)
  glide(tl, hand, [820, 560], [652, 377], typed + 0.1, 0.7)
  press(tl, hand, q('.sd-go'), typed + 0.9)
  const F = typed + 1.15
  tl.to(hand, { opacity: 0, duration: 0.2 }, F)
  tl.to(q('.sd-body'), { opacity: 0, duration: 0.15 }, F)
  tl.to(card, { width: 600, height: 44, borderRadius: 22, y: -228, duration: 0.6, ease: 'expo.inOut' }, F)
  tl.fromTo(q('.sd-soft'), { opacity: 0 }, { opacity: 1, duration: 0.3 }, F + 0.1)
  tl.fromTo(q('.sd-pill'), { opacity: 0 }, { opacity: 1, duration: 0.3 }, F + 0.45)
  tl.fromTo(q('.sd-pill .psd-spin'), { rotation: 0 }, { rotation: 720, duration: 3.6, ease: 'none' }, F)

  // The four stages, each finishing in turn while the status word changes.
  const P = F + 0.55
  tl.fromTo(q('.sd-progress'), { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.45, ease: 'expo.out' }, P)
  const words = qa('.sd-pill .psd-sw')
  qa('.sd-row').forEach((row, i) => {
    const s = P + 0.15 + i * 0.75
    tl.fromTo(words[i], { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.25 }, s)
    shimmer(tl, [...words[i].querySelectorAll('span')], s + 0.15)
    if (i < 3) tl.to(words[i], { opacity: 0, y: -10, duration: 0.2 }, s + 0.6)
    tl.to(row.querySelector('.sd-ring'), { borderColor: '#3bb8c3', duration: 0.15 }, s)
    tl.fromTo(row.querySelector('.sd-detail'), { opacity: 0 }, { opacity: 1, duration: 0.3 }, s + 0.1)
    tl.fromTo(row.querySelector('.sd-ok'), { opacity: 0, scale: 0.5 }, { opacity: 1, scale: 1, duration: 0.3, ease: 'back.out(3)' }, s + 0.6)
  })

  // Ranked papers, each with the reason it ranks.
  const R = P + 3.4
  tl.to([q('.sd-progress'), card], { opacity: 0, y: '-=12', duration: 0.3, ease: 'power2.in' }, R)
  tl.fromTo(q('.sd-head'), { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.35 }, R + 0.2)
  qa('.sd-result').forEach((c, i) => {
    tl.fromTo(c, { clipPath: 'circle(0px at 34px 50%)' }, { clipPath: 'circle(900px at 34px 50%)', duration: 0.75, ease: 'expo.inOut' }, R + 0.3 + i * 0.2)
    tl.fromTo(c.querySelector('.psd-score'), { scale: 0.4 }, { scale: 1, duration: 0.35, ease: 'back.out(3)' }, R + 0.6 + i * 0.2)
  })
  qa('.sd-result .psd-mark').forEach((m, i) => tl.to(m, { backgroundSize: '100% 100%', duration: 0.55, ease: 'power2.inOut' }, R + 1.2 + i * 0.35))
  tl.addLabel('end', R + 2.4)
  tl.to(q('.sd-all'), { opacity: 0, duration: 0.4 }, R + 4.6)
  return tl
})
</script>

<template>
  <div class="psd" :class="{ zh }">
    <div class="psd-top"><i /><i /><i /><b>{{ t('Search', '检索') }}</b><span>/ {{ t('New search', '新建检索') }}</span><span class="psd-tag">{{ t('ILLUSTRATION', '示意') }}</span></div>
    <div ref="frame" class="psd-frame" :style="{ height: `${H * scale}px` }">
      <div ref="stage" class="psd-stage" :style="{ width: `${W}px`, height: `${H}px`, transform: `scale(${scale})` }" aria-hidden="true">
        <div class="sd-all">
          <div class="sd-center">
            <div class="sd-card">
              <div class="sd-soft" /><div class="sd-teal" />
              <div class="sd-body">
                <div class="sd-label">{{ t('Research question', '研究问题') }}</div>
                <div class="sd-ta"><div class="sd-ph">{{ t('Enter a research question, a research-gap paragraph or a natural-language intent…', '输入研究问题、研究空白段落或自然语言意图…') }}</div><span class="sd-q chars"><span v-for="(c, i) in [...question]" :key="i">{{ c }}</span></span><i class="sd-caret" /></div>
                <div class="sd-opts"><div><small>{{ t('Data source', '数据源') }}</small><span>OpenAlex<em>⌄</em></span></div><div><small>{{ t('Search budget', '检索预算') }}</small><span>{{ t('Auto · Recommended', '自动 · 推荐') }}<em>⌄</em></span></div></div>
                <div class="sd-foot"><span>{{ t('Reset to defaults', '恢复默认') }}</span><span class="psd-btn sd-go">{{ t('Start search', '开始检索') }}</span></div>
              </div>
              <div class="sd-pill"><span class="psd-spin"><i v-for="k in 12" :key="k" :style="{ transform: `rotate(${k * 30}deg)`, opacity: 0.25 + k / 16 }" /></span><span class="sd-pq">{{ question }}</span><span class="sd-st"><span v-for="(s, i) in statuses" :key="i" class="psd-sw"><span v-for="(c, k) in [...s]" :key="k">{{ c }}</span></span></span></div>
            </div>
          </div>
          <div class="sd-progress">
            <div v-for="(s, i) in stages" :key="i" class="sd-row"><span class="sd-ic"><span class="sd-ring" /><span class="sd-ok">✓</span></span><b>{{ s[0] }}</b><span class="sd-detail">{{ s[1] }}</span></div>
          </div>
          <div class="sd-head">{{ t('6 papers · ranked by relevance', '6 篇文献 · 按相关度排序') }}</div>
          <div v-for="(p, i) in papers" :key="i" class="sd-result" :style="{ top: `${112 + i * 134}px` }">
            <span class="sd-cb" /><h5>{{ p.title }}</h5><div class="sd-meta">{{ p.meta }}</div>
            <div class="sd-why"><b>{{ t('Why it ranks', '排序理由') }}</b> · <span class="psd-mark">{{ p.why }}</span></div>
            <span class="psd-score">{{ p.score }}/10</span><span class="sd-cites">{{ t(`${p.cites} citations`, `被引 ${p.cites}`) }}</span>
          </div>
          <div class="psd-cursor" v-html="HAND" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sd-all { position: absolute; inset: 0; }
.sd-center { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; }
.sd-card { position: relative; flex: none; width: 600px; height: 290px; border-radius: 16px; background: var(--d-bg); box-shadow: 0 18px 50px rgb(0 0 0 / .08), 0 0 0 1px var(--d-border); overflow: hidden; }
.sd-teal, .sd-soft { position: absolute; inset: 0; border-radius: inherit; }
.sd-teal { background: var(--d-teal); }
.sd-soft { background: var(--d-soft); opacity: 0; }
.sd-body { position: absolute; left: 50%; top: 50%; width: 600px; height: 290px; margin: -145px 0 0 -300px; padding: 24px; }
.sd-label { font-size: 13px; font-weight: 600; }
.sd-ta { position: relative; margin-top: 10px; height: 96px; border: 1.5px solid var(--d-border); border-radius: 12px; padding: 12px 14px; font-size: 17px; line-height: 1.45; }
.sd-ph { position: absolute; left: 14px; right: 14px; top: 12px; color: var(--d-muted); opacity: .7; font-size: 15px; }
.sd-caret { display: inline-block; width: 2px; height: 20px; background: var(--d-teal); vertical-align: -4px; margin-left: 1px; }
.sd-opts { display: flex; gap: 16px; margin-top: 14px; }
.sd-opts > div { flex: 1; }
.sd-opts small { display: block; font-size: 11px; font-weight: 600; margin-bottom: 5px; }
.sd-opts span { display: flex; justify-content: space-between; height: 34px; align-items: center; padding: 0 12px; border: 1.5px solid var(--d-border); border-radius: 9px; font-size: 13px; }
.sd-opts em { font-style: normal; color: var(--d-muted); }
.sd-foot { position: absolute; left: 24px; right: 24px; bottom: 20px; display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: var(--d-muted); }
.sd-go { width: 128px; height: 36px; font-size: 13px; }
.sd-pill { position: absolute; inset: 0; display: flex; align-items: center; gap: 12px; padding: 0 18px; font-size: 13px; opacity: 0; white-space: nowrap; }
.sd-pq { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; color: var(--d-muted); }
.sd-st { position: relative; width: 220px; height: 20px; flex: none; border-left: 1px solid var(--d-border); }
.sd-progress { position: absolute; left: 150px; top: 100px; width: 580px; border: 1px solid var(--d-border); border-radius: 14px; background: var(--d-bg); padding: 6px 0; opacity: 0; box-shadow: 0 14px 40px rgb(0 0 0 / .05); }
.sd-row { display: flex; align-items: center; gap: 14px; height: 62px; padding: 0 22px; }
.sd-row + .sd-row { border-top: 1px solid var(--d-line); }
.sd-row b { width: 170px; font-size: 14px; font-weight: 600; flex: none; }
.zh .sd-row b { width: 150px; }
.sd-ic { position: relative; width: 22px; height: 22px; flex: none; }
.sd-ring { position: absolute; inset: 0; border: 2px solid var(--d-border); border-radius: 50%; }
.sd-ok { position: absolute; inset: 0; border-radius: 50%; background: var(--d-ink); color: var(--d-inv); font-size: 12px; font-weight: 700; display: flex; align-items: center; justify-content: center; opacity: 0; }
.sd-detail { font-size: 12.5px; color: var(--d-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; opacity: 0; }
.sd-head { position: absolute; left: 100px; top: 74px; font-size: 13px; color: var(--d-muted); opacity: 0; }
.sd-result { position: absolute; left: 100px; width: 680px; height: 120px; border: 1px solid var(--d-border); border-radius: 13px; background: var(--d-bg); padding: 14px 18px 0 46px; box-shadow: 0 1px 3px rgb(0 0 0 / .04); clip-path: circle(0px at 34px 50%); }
.sd-cb { position: absolute; left: 18px; top: 18px; width: 14px; height: 14px; border: 1.5px solid var(--d-border); border-radius: 4px; }
.sd-result h5 { margin: 0; font-size: 14.5px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sd-meta { font-size: 11.5px; color: var(--d-muted); margin-top: 4px; }
.sd-why { font-size: 12.5px; margin-top: 10px; }
.sd-why b { font-weight: 600; }
.sd-result .psd-score { position: absolute; left: 46px; bottom: 12px; }
.sd-cites { position: absolute; right: 18px; bottom: 14px; font-size: 11px; color: var(--d-muted); }
</style>
