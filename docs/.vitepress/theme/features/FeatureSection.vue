<script setup lang="ts">
defineProps<{
  id: string
  index: string
  eyebrow: string
  title: string
  body: string
  points: string[]
  href: string
  linkText: string
  badge?: string
  reverse?: boolean
  note?: string
}>()
</script>

<template>
  <section class="ps-feature ps-container" :class="{ reverse }" :aria-labelledby="`${id}-heading`">
    <div class="ps-feature-copy">
      <p class="ps-feature-eyebrow"><span>{{ index }}</span>{{ eyebrow }}<small v-if="badge">{{ badge }}</small></p>
      <h2 :id="`${id}-heading`">{{ title }}</h2>
      <p class="ps-feature-body">{{ body }}</p>
      <ul>
        <li v-for="point in points" :key="point">{{ point }}</li>
      </ul>
      <a class="ps-text-link" :href="href">{{ linkText }} →</a>
    </div>
    <div class="ps-feature-demo">
      <slot />
    </div>
    <p v-if="note" class="ps-features-note">{{ note }}</p>
  </section>
</template>
