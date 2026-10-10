<script setup lang="ts">
// Real screens of the workspace; regenerate with web/tests/docs/screenshots.spec.ts.
import { ref } from 'vue'
import { withBase } from 'vitepress'
const props = defineProps<{ zh: boolean }>()
const active = ref(0)
const t = (en: string, cn: string) => props.zh ? cn : en
const views = [
  { image: 'search', label: ['Search', '检索'], alt: ['New search form with a research question', '填写了研究问题的新建检索表单'] },
  { image: 'results', label: ['Results', '结果'], alt: ['Ranked papers with scores and ranking reasons', '带评分与排序理由的文献列表'] },
  { image: 'bibliometrics', label: ['Bibliometrics', '文献计量'], alt: ['Bibliometric overview of the retrieved corpus', '候选集的文献计量概览'] },
  { image: 'review', label: ['Review', '综述'], alt: ['A drafted review with linked citations', '带关联引用的综述正文'] },
] as const
function moveTab(event: KeyboardEvent, index: number) {
  const count = views.length
  const next = event.key === 'ArrowRight' ? (index + 1) % count : event.key === 'ArrowLeft' ? (index + count - 1) % count
    : event.key === 'Home' ? 0 : event.key === 'End' ? count - 1 : null
  if (next === null) return
  event.preventDefault()
  active.value = next
  const tabs = (event.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLButtonElement>('[role=tab]')
  tabs?.[next].focus()
}
</script>

<template>
  <div class="ps-tour">
    <div class="ps-tour-tabs" role="tablist" :aria-label="t('Explore the workspace', '探索工作区')">
      <button v-for="(view, index) in views" :id="`tour-tab-${index}`" :key="view.image" role="tab" :aria-selected="active === index"
        :aria-controls="`tour-panel-${index}`" :tabindex="active === index ? 0 : -1" @click="active = index" @keydown="moveTab($event, index)">
        {{ t(...view.label) }}<small v-if="view.image === 'review'">{{ t('Experimental', '实验性') }}</small>
      </button>
    </div>
    <div v-for="(view, index) in views" v-show="active === index" :id="`tour-panel-${index}`" :key="view.image" role="tabpanel"
      :aria-labelledby="`tour-tab-${index}`" tabindex="0" class="ps-tour-panel">
      <img :src="withBase(`/images/workspace-${view.image}-${zh ? 'zh' : 'en'}.png`)" :alt="t(...view.alt)" width="1440" height="900" loading="lazy">
    </div>
  </div>
</template>
