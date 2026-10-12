<script setup lang="ts">
import { computed } from 'vue'
import { useData, withBase } from 'vitepress'

const { lang } = useData()
const zh = computed(() => lang.value.startsWith('zh'))
const options = computed(() => [
  {
    key: 'online',
    title: zh.value ? '在线使用' : 'Use online',
    description: zh.value ? '打开浏览器即可开始研究，使用每日积分或连接自己的模型密钥。' : 'Start researching in your browser with daily credits or your own model keys.',
    badge: zh.value ? '无需安装' : 'No installation required',
    action: zh.value ? '在线快速开始' : 'Quick start online'
  },
  {
    key: 'local',
    title: zh.value ? '在本地运行' : 'Run locally',
    description: zh.value ? '在自己的电脑或服务器上运行社区版，连接模型，并在本地保存研究记录。' : 'Run the community edition on your computer or server, connect a model, and keep research records locally.',
    badge: zh.value ? '开源 · 自主部署' : 'Open source · Self-hosted',
    action: zh.value ? '本地快速开始' : 'Quick start local'
  }
])
</script>

<template>
  <div class="ps-start-options">
    <a v-for="option in options" :key="option.key" class="ps-start-option"
      :href="withBase(`${zh ? '/zh' : ''}/get-started/${option.key}`)"
      :aria-label="option.action">
      <div class="ps-start-art" :class="option.key" aria-hidden="true">
        <svg viewBox="0 0 440 240" fill="none" focusable="false">
          <rect x="42" y="40" width="356" height="226" rx="15" stroke="currentColor" stroke-width="1.2" />
          <path d="M42 77H398" stroke="currentColor" stroke-opacity=".55" />
          <g stroke="currentColor" stroke-opacity=".65"><circle cx="61" cy="59" r="4" /><circle cx="76" cy="59" r="4" /><circle cx="91" cy="59" r="4" /></g>
          <template v-if="option.key === 'online'">
            <rect x="133" y="49" width="208" height="20" rx="10" stroke="currentColor" stroke-opacity=".4" />
            <text x="237" y="63" text-anchor="middle" fill="currentColor" font-size="11">paperseek.app</text>
            <path d="M91 103H114L124 113V147H91ZM114 103V113H124M99 125H116M99 133H111" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M145 115H266M145 132H228" stroke="currentColor" stroke-opacity=".75" stroke-width="1.5" stroke-linecap="round" />
            <rect x="84" y="166" width="272" height="43" rx="11" stroke="currentColor" stroke-opacity=".55" />
            <path d="M101 187H247M324 181L330 187L324 193M318 187H330" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </template>
          <template v-else>
            <text x="374" y="63" text-anchor="end" fill="currentColor" font-size="11">localhost</text>
            <path d="M42 77H119V266" stroke="currentColor" stroke-opacity=".4" />
            <path d="M60 107H98M60 126H88M60 159H98M60 178H88M60 197H92" stroke="currentColor" stroke-opacity=".6" stroke-width="1.5" stroke-linecap="round" />
            <rect x="147" y="100" width="226" height="134" rx="10" stroke="currentColor" stroke-opacity=".55" />
            <path d="M165 122L172 129L165 136M181 136H197" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M166 161H334M166 179H310M166 197H269" stroke="currentColor" stroke-opacity=".6" stroke-width="1.5" stroke-linecap="round" />
          </template>
        </svg>
      </div>
      <div class="ps-start-copy">
        <strong>{{ option.title }}<span class="ps-start-arrow" aria-hidden="true">↗</span></strong>
        <p>{{ option.description }}</p>
        <span class="ps-start-badge">{{ option.badge }}</span>
      </div>
    </a>
  </div>
</template>

<style scoped>
.ps-start-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; margin: 28px 0 32px; }
.ps-start-options .ps-start-option { display: flex; flex-direction: column; overflow: hidden; border: 1px solid var(--vp-c-divider); border-radius: 16px; color: var(--vp-c-text-1); text-decoration: none; font-weight: 400; transition: border-color .18s, box-shadow .18s; }
.ps-start-option:hover { border-color: var(--vp-c-text-3); box-shadow: 0 4px 18px rgb(0 0 0 / .04); }
.ps-start-art { overflow: hidden; border-bottom: 1px solid var(--vp-c-divider); background: var(--vp-c-bg); color: var(--vp-c-text-2); }
.ps-start-art svg { display: block; width: 100%; }
.ps-start-copy { display: flex; flex-direction: column; align-items: flex-start; flex: 1; padding: 22px; }
.ps-start-copy strong { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; font-size: 19px; font-weight: 550; line-height: 1.5; }
.ps-start-arrow { color: var(--vp-c-text-3); font-size: 20px; font-weight: 400; }
.ps-start-options .ps-start-copy p { flex: 1; margin: 12px 0 20px; color: var(--vp-c-text-2); font-size: 15px; line-height: 1.8; }
.ps-start-badge { border-radius: 999px; padding: 3px 10px; background: var(--vp-c-bg-soft); color: var(--vp-c-text-2); font-size: 12px; line-height: 1.8; }
@media (max-width: 639px) { .ps-start-options { grid-template-columns: 1fr; gap: 18px; } }
</style>
