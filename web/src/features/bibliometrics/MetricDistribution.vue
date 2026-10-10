<script setup lang="ts">
// Card with horizontal bars (or a year column chart when chronological).
import { computed, ref } from "vue";
import type { MetricBucket } from "./api";
import { useMetricMessages } from "./messages";
import { useUi } from "../../locales/ui";

const props = withDefaults(defineProps<{ title: string; items: MetricBucket[]; total?: number; chronological?: boolean; limit?: number; columns?: boolean }>(), { limit: 5 });
const { m } = useMetricMessages();
const u = useUi();
const all = ref(false);
const shown = computed(() => (props.chronological || all.value ? props.items : props.items.slice(0, props.limit)));
const maximum = computed(() => Math.max(1, ...shown.value.map((item) => item.count)));
const count = computed(() => props.total || props.items.length);
const range = computed(() => (props.items.length ? `${props.items[0].label} – ${props.items[props.items.length - 1].label}` : ""));
</script>

<template>
  <section class="card c">
    <div class="card-header">
      <div>
        <h2 class="card-title">{{ title }}</h2>
        <p v-if="chronological && range" class="card-desc">{{ range }}</p>
        <p v-else-if="!chronological && count > shown.length" class="card-desc">{{ u("topN", { n: shown.length, total: count.toLocaleString() }) }}</p>
      </div>
      <button v-if="!chronological && items.length > limit" class="btn btn-ghost btn-sm" type="button" style="height: 28px; margin: -4px -8px 0 0" @click="all = !all">{{ all ? u("showLess") : u("showAll") }}</button>
    </div>
    <div class="card-content">
      <p v-if="!shown.length" class="sm muted">{{ m("noData") }}</p>
      <template v-else-if="chronological">
        <div class="bars" role="img" :aria-label="title">
          <div v-for="item in shown" :key="item.label" class="bar-col" :title="`${item.label}: ${item.count}`">
            <span class="bar-label">{{ item.count.toLocaleString() }}</span>
            <span class="bar" :style="{ height: `${Math.max(2, (item.count / maximum) * 140)}px` }"></span>
          </div>
        </div>
        <div class="axis" aria-hidden="true"><span v-for="item in shown" :key="item.label">{{ shown.length > 12 ? String(item.label).slice(-2) : item.label }}</span></div>
      </template>
      <div v-else :class="{ 'grid-2': columns }" :style="columns ? 'gap: 0 32px' : undefined">
        <div v-for="item in shown" :key="item.label" class="hbar">
          <span :title="item.label">{{ item.label }}</span>
          <span class="meter"><span :style="{ width: `${(item.count / maximum) * 100}%` }"></span></span>
          <span>{{ item.count.toLocaleString() }}</span>
        </div>
      </div>
    </div>
  </section>
</template>
