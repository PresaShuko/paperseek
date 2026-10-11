<script setup lang="ts">
import { ref } from 'vue'
import { withBase } from 'vitepress'
const props = defineProps<{ zh: boolean }>()
const active = ref(0)
const t = (en: string, cn: string) => props.zh ? cn : en
const labels = [['Search', '检索'], ['Bibliometrics', '文献计量'], ['Review', '综述']] as const
const stages = [['Understand the question', '理解研究问题'], ['Refine the search', '调整检索策略'], ['Retrieve & rank papers', '召回与排序文献'], ['Build a reading list', '整理阅读清单']]
function moveTab(event: KeyboardEvent, index: number) {
  const next = event.key === 'ArrowRight' ? (index + 1) % 3 : event.key === 'ArrowLeft' ? (index + 2) % 3 : event.key === 'Home' ? 0 : event.key === 'End' ? 2 : null
  if (next === null) return
  event.preventDefault()
  active.value = next
  const tabs = (event.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLButtonElement>('[role=tab]')
  tabs?.[next].focus()
}
</script>

<template>
  <div class="ps-tour">
    <div class="ps-tour-top"><div class="ps-tour-brand"><img class="ps-light-only" :src="withBase('/paperseek-lockup.svg')" alt="PaperSeek" width="158" height="20"><img class="ps-dark-only" :src="withBase('/paperseek-lockup-dark.svg')" alt="PaperSeek" width="158" height="20"><span> / {{ t('Workspace', '工作区') }}</span></div><span class="ps-demo-label">{{ t('INTERACTIVE PREVIEW', '交互式预览') }}</span></div>
    <div class="ps-tour-tabs" role="tablist" :aria-label="t('Explore the workspace', '探索工作区')"><button v-for="(label, index) in labels" :key="index" :id="`tour-tab-${index}`" role="tab" :aria-selected="active === index" :aria-controls="`tour-panel-${index}`" :tabindex="active === index ? 0 : -1" @click="active = index" @keydown="moveTab($event, index)">{{ t(...label) }}<small v-if="index === 2">{{ t('Experimental', '实验性') }}</small></button></div>
    <div v-for="(_, index) in labels" v-show="active === index" :key="index" :id="`tour-panel-${index}`" role="tabpanel" :aria-labelledby="`tour-tab-${index}`" tabindex="0" class="ps-tour-panel">
      <template v-if="index === 0">
        <div class="ps-demo-search">
          <div class="ps-demo-form"><p class="ps-demo-title">{{ t('Literature search', '文献检索') }}</p><p class="ps-demo-muted">{{ t('Begin with the question on your mind.', '从你关心的研究问题开始。') }}</p><div class="ps-demo-input"><span>{{ t('How does open-source software sustain its development?', '开源软件如何获得持续的开发支持？') }}</span><div><small>{{ t('Balanced', '均衡') }} ⌄</small><span class="ps-demo-submit" aria-hidden="true">↑</span></div></div><div class="ps-demo-settings"><span>{{ t('Data source', '数据源') }}</span><strong>OpenAlex <span aria-hidden="true">⌄</span></strong></div><div class="ps-demo-settings"><span>{{ t('Research field', '研究领域') }}</span><strong>{{ t('All fields', '不限') }} <span aria-hidden="true">⌄</span></strong></div><div class="ps-demo-check"><span aria-hidden="true">✓</span>{{ t('Explore citation connections', '探索引用关系') }}</div></div>
          <div class="ps-demo-flow"><p class="ps-demo-title">{{ t('A visible path to the literature', '看得见的检索过程') }}</p><div v-for="(stage, i) in stages" :key="i" class="ps-demo-stage"><span>{{ `0${i + 1}` }}</span><div><strong>{{ t(stage[0], stage[1]) }}</strong><div class="ps-demo-line"/><div class="ps-demo-line short"/></div><b aria-hidden="true">↗</b></div></div>
        </div>
      </template>
      <template v-else-if="index === 1">
        <div class="ps-demo-map"><div class="ps-map-copy"><p class="ps-eyebrow">{{ t('EXPLORE THE CORPUS', '观察候选集') }}</p><h3>{{ t('A reading list,', '一份阅读清单，') }}<br>{{ t('with a wider view.', '更广阔的研究视野。') }}</h3><p>{{ t('Explore distributions, native keywords, and shared-reference relations across the retrieved corpus. Networks are generated on demand.', '查看实际获取候选集的分布、原生关键词和共同参考文献关系，按需生成网络。') }}</p><div class="ps-map-key"><i/>{{ t('Corpus papers', '候选文献') }}<i/>{{ t('Shared references', '共同参考文献') }}</div></div><svg viewBox="0 0 520 340" role="img" :aria-label="t('Illustrative network of connected papers', '文献关联网络示意图')"><g stroke="currentColor" opacity=".25"><path d="M260 160L135 95M260 160L380 70M260 160L370 253M260 160L112 246M260 160L250 290M135 95L60 158M135 95L189 35M380 70L457 164M370 253L457 164M112 246L60 158M370 253L455 302M260 160L290 40M260 160L430 195"/></g><g class="ps-graph-nodes"><circle cx="260" cy="160" r="21" class="main"/><circle cx="135" cy="95" r="13"/><circle cx="380" cy="70" r="12"/><circle cx="370" cy="253" r="16"/><circle cx="112" cy="246" r="10"/><circle cx="250" cy="290" r="8"/><circle cx="60" cy="158" r="7"/><circle cx="189" cy="35" r="7"/><circle cx="457" cy="164" r="9"/><circle cx="455" cy="302" r="7"/><circle cx="290" cy="40" r="6"/><circle cx="430" cy="195" r="7"/></g><g fill="currentColor" font-size="12"><text x="290" y="164">{{ t('Corpus', '候选集') }}</text><text x="92" y="71">{{ t('Related papers', '关联文献') }}</text><text x="325" y="284">{{ t('Connected group', '连通分组') }}</text></g></svg></div>
      </template>
      <template v-else>
        <div class="ps-demo-review"><aside><p class="ps-eyebrow">{{ t('YOUR OUTLINE', '你的大纲') }}</p><div v-for="(item, i) in [['The research landscape', '研究背景'], ['Themes in the literature', '文献中的主要主题'], ['Connecting the findings', '综合研究发现']]" :key="i"><span>{{ `0${i+1}` }}</span>{{ t(item[0],item[1]) }}</div><p class="ps-demo-muted">{{ t('Shape the outline before writing.', '确认大纲，再开始写作。') }}</p></aside><div class="ps-demo-document"><div class="ps-document-meta">{{ t('ABSTRACT-BASED REVIEW', '基于摘要的文献综述') }}<span>{{ t('Draft', '草稿') }}</span></div><h3>{{ t('Bring the literature', '将分散的文献，') }}<br>{{ t('into conversation.', '整理成有条理的综述。') }}</h3><p>{{ t('Build a thematic outline from selected papers. Draft, edit, and revisit individual sections with citations connected to the source evidence.', '从选定文献出发组织主题大纲。生成、编辑或重写单个章节，并保留引文与原始证据的关联。') }}</p><div class="ps-demo-line"/><div class="ps-demo-line"/><div class="ps-demo-line short"/><div class="ps-document-formats">Markdown <span>/</span> Word <span>/</span> BibTeX</div></div></div>
      </template>
    </div>
  </div>
</template>
