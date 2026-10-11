<script setup lang="ts">
// The homepage hero paints itself in watercolour (public/hero-painting.html).
// The finished still (hero.jpg, from docs/.vitepress/hero-poster.mjs) shows until the painting starts, and stays if
// scripts, WebGL or the iframe are unavailable.
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'
// Relative paths: neither package exports its browser build as a subpath.
import p5Url from '../../../node_modules/p5/lib/p5.min.js?url'
import brushUrl from '../../../node_modules/p5.brush/dist/p5.brush.js?url'
import fontUrl from '../../../node_modules/@fontsource-variable/geist/files/geist-latin-wght-normal.woff2?url'

const src = ref('')
const painting = ref(false)

function onMessage(event: MessageEvent) {
  if (event.origin !== window.location.origin || event.data?.source !== 'paperseek-hero') return
  if (event.data.state === 'painting' || event.data.state === 'done') painting.value = true
}

onMounted(() => {
  window.addEventListener('message', onMessage)
  const absolute = (url: string) => new URL(url, window.location.href).href
  const query = new URLSearchParams({ p5: absolute(p5Url), brush: absolute(brushUrl), font: absolute(fontUrl) })
  src.value = `${withBase('/hero-painting.html')}?${query}`
})
onBeforeUnmount(() => window.removeEventListener('message', onMessage))
</script>

<template>
  <div class="ps-hero-art">
    <img :src="withBase('/images/hero.jpg')" alt="" width="2400" height="840" fetchpriority="high">
    <iframe v-if="src" :src="src" :class="{ painting }" title="" aria-hidden="true" tabindex="-1" loading="eager"></iframe>
  </div>
</template>
