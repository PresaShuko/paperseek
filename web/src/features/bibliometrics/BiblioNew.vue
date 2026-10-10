<script setup lang="ts">
import { onBeforeUnmount, ref, watchEffect } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError } from "../../api/client";
import Icon from "../../components/Icon.vue";
import { useUi } from "../../locales/ui";
import SourceRunPicker from "../workspace/SourceRunPicker.vue";
import { invalidateHistory, listPaths, setHeader } from "../workspace/state";
import { metricsApi } from "./api";
import { useMetricMessages } from "./messages";

const route = useRoute();
const router = useRouter();
const u = useUi();
const { m } = useMetricMessages();
const source = ref(typeof route.query.source === "string" ? route.query.source : "");
const busy = ref(false);
const error = ref("");
let key = crypto.randomUUID();
let alive = true;
watchEffect(() => setHeader(u("newAnalysis"), { label: u("bibliometrics"), to: listPaths.bibliometrics }));
onBeforeUnmount(() => (alive = false));
function select(id: string) {
  if (id !== source.value) key = crypto.randomUUID();
  source.value = id;
}
async function create() {
  if (!source.value || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const value = await metricsApi.create(source.value, key);
    invalidateHistory("bibliometrics");
    if (alive) await router.push(`/bibliometrics/${value.id}`);
  } catch (e) {
    error.value = e instanceof ApiError && m(e.code) !== e.code ? e.code : "error";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="page create">
    <form class="card create-card" aria-labelledby="new-analysis-title" @submit.prevent="create">
      <div class="ch">
        <div><h2 id="new-analysis-title">{{ u("newAnalysis") }}</h2><p>{{ u("newAnalysisDesc") }}</p></div>
      </div>
      <div class="cc">
        <div class="field">
          <span class="label">{{ u("sourceSearch") }}</span>
          <SourceRunPicker :minimum="0" :selected="source" :label="u('sourceSearch')" @select="select" />
          <p class="help">{{ u("analysisNote") }}</p>
        </div>
        <div v-if="error" class="alert" role="alert" style="grid-template-columns: 16px 1fr"><Icon name="fail" /><p class="alert-title">{{ m(error) }}</p></div>
      </div>
      <div class="cf">
        <RouterLink class="btn btn-ghost btn-sm" :to="listPaths.bibliometrics">{{ u("cancel") }}</RouterLink>
        <button class="btn btn-sm" type="submit" :disabled="!source || busy"><Icon v-if="busy" name="loader" />{{ busy ? u("creating") : u("startAnalysis") }}</button>
      </div>
    </form>
  </main>
</template>
