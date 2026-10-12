<script setup lang="ts">
// Row actions for saved records: optional extra links, rename, export, delete.
import { ref } from "vue";
import AppDialog from "../../components/AppDialog.vue";
import Icon from "../../components/Icon.vue";
import UiMenu from "../../components/UiMenu.vue";
import { toast } from "../../components/toast";
import { useUi } from "../../locales/ui";
import { exportRecord, removeRecord, renameRecord, type HistoryRecord } from "./history-api";
import { invalidateHistory, type WorkspaceModule } from "./state";

const props = defineProps<{ module: WorkspaceModule; record: HistoryRecord; label?: string }>();
const emit = defineEmits<{ changed: [action: "rename" | "remove"] }>();
const u = useUi();
const editing = ref<"rename" | "remove" | null>(null);
const name = ref("");
const busy = ref(false);
const error = ref(false);
function edit(action: "rename" | "remove") {
  name.value = props.record.title;
  error.value = false;
  editing.value = action;
}
async function save() {
  if (busy.value || !editing.value) return;
  const action = editing.value;
  busy.value = true;
  error.value = false;
  try {
    if (action === "rename") await renameRecord(props.module, props.record.id, name.value.trim());
    else await removeRecord(props.module, props.record.id);
    editing.value = null;
    invalidateHistory(props.module);
    toast(u(action === "rename" ? "savedToast" : "deletedToast"), { tone: "ok" });
    emit("changed", action);
  } catch {
    error.value = true;
  } finally {
    busy.value = false;
  }
}
async function download() {
  try {
    await exportRecord(props.module, props.record.id);
  } catch {
    toast(u("actionFailed"), { tone: "fail" });
  }
}
</script>

<template>
  <UiMenu :label="label || `${u('more')} · ${record.title}`" align="end" :min-width="168">
    <template #trigger><Icon name="ellipsis" /></template>
    <slot />
    <button class="opt" role="menuitem" data-menu-item type="button" @click="edit('rename')"><Icon name="pencil" />{{ u("rename") }}</button>
    <button class="opt" role="menuitem" data-menu-item type="button" @click="download"><Icon name="download" />{{ u("export") }}</button>
    <div class="opt-sep" role="separator"></div>
    <button class="opt danger" role="menuitem" data-menu-item type="button" :disabled="record.active" @click="edit('remove')"><Icon name="trash" />{{ u("remove") }}</button>
  </UiMenu>
  <AppDialog v-if="editing === 'rename'" :title="u('rename')" :busy="busy" @close="editing = null">
    <form id="rename-form" class="field" @submit.prevent="save">
      <label class="label" for="rename-input">{{ u("displayTitle") }}</label>
      <input id="rename-input" v-model="name" class="input" required maxlength="200" autofocus />
      <p v-if="error" class="help danger-text" role="alert">{{ u("actionFailed") }}</p>
    </form>
    <template #footer>
      <button class="btn btn-outline btn-sm" type="button" :disabled="busy" @click="editing = null">{{ u("cancel") }}</button>
      <button class="btn btn-sm" type="submit" form="rename-form" :disabled="busy || !name.trim()">{{ u("save") }}</button>
    </template>
  </AppDialog>
  <AppDialog v-if="editing === 'remove'" :title="u('deleteTitle')" :description="u('deleteHint')" :busy="busy" @close="editing = null">
    <p class="sm medium">{{ record.title }}</p>
    <p v-if="error" class="help danger-text" role="alert">{{ u("actionFailed") }}</p>
    <template #footer>
      <button class="btn btn-outline btn-sm" type="button" :disabled="busy" @click="editing = null">{{ u("cancel") }}</button>
      <button class="btn btn-destructive btn-sm" type="button" :disabled="busy" @click="save">{{ u("remove") }}</button>
    </template>
  </AppDialog>
</template>
