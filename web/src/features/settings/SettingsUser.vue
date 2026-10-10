<script setup lang="ts">
// Settings › User (Community): where local data lives, saved keys, and data management.
import { computed, onMounted, ref } from "vue";
import { json } from "../../api/client";
import type { components } from "../../api/generated";
import { toast } from "../../components/toast";
import { useUi } from "../../locales/ui";
import DataManagement from "./DataManagement.vue";
import { workspaceSettings } from "./store";

const u = useUi();
const location = ref("");
const keys = computed(() => ({
  connections: workspaceSettings.connections.length,
  sources: workspaceSettings.sources.filter((item) => item.key_origin === "settings").length,
}));
onMounted(async () => {
  try {
    location.value = (await json<components["schemas"]["WorkspaceSummary"]>("/api/v1/data/summary")).location || "";
  } catch {
    location.value = "";
  }
});
async function copyPath() {
  try {
    await navigator.clipboard.writeText(location.value);
    toast(u("pathCopied"), { tone: "ok" });
  } catch {
    toast(u("copyFailed"), { tone: "fail" });
  }
}
</script>

<template>
  <div class="stack" style="gap: 24px; max-width: 880px">
    <section class="card c" aria-labelledby="local-title">
      <div class="card-header"><div><h2 id="local-title" class="card-title">{{ u("localData") }}</h2><p class="help" style="margin-top: 4px">{{ u("localDataDesc") }}</p></div></div>
      <div class="card-content stack" style="gap: 0">
        <div class="setrow">
          <span class="stack" style="gap: 2px"><span class="sm medium">{{ u("dataLocation") }}</span><span class="xs muted">{{ u("dataLocationDesc") }}</span></span>
          <span class="row" style="gap: 4px; flex-wrap: nowrap; min-width: 0"><span class="sm mono muted truncate" style="margin-right: 8px">{{ location || "—" }}</span><button class="btn btn-ghost btn-sm" type="button" style="height: 28px" :disabled="!location" @click="copyPath">{{ u("copyPath") }}</button></span>
        </div>
        <div class="setrow">
          <span class="stack" style="gap: 2px"><span class="sm medium">{{ u("savedKeys") }}</span><span class="xs muted">{{ u("savedKeysDesc", keys) }}</span></span>
          <RouterLink class="btn btn-ghost btn-sm" to="/settings/models" style="height: 28px">{{ u("manage") }}</RouterLink>
        </div>
      </div>
    </section>
    <DataManagement />
  </div>
</template>
