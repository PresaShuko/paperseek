<script setup lang="ts">
// Destructive confirmation: the action stays disabled until the phrase is typed exactly.
import { computed, ref } from "vue";
import AppDialog from "../../components/AppDialog.vue";
import Icon from "../../components/Icon.vue";
import { useUi } from "../../locales/ui";

const props = defineProps<{ title: string; description: string; phrase: string; action: string; busy?: boolean; status?: string; error?: string }>();
const emit = defineEmits<{ confirm: []; close: [] }>();
const u = useUi();
const typed = ref("");
const ready = computed(() => typed.value.trim() === props.phrase && !props.busy);
</script>

<template>
  <AppDialog :title="title" :description="description" :busy="busy" @close="emit('close')">
    <div class="field">
      <label class="label" for="confirm-phrase">{{ u("typeToConfirm", { phrase }) }}</label>
      <input id="confirm-phrase" v-model="typed" class="input" autocomplete="off" spellcheck="false" autofocus :disabled="busy" @keydown.enter.prevent="ready && emit('confirm')" />
    </div>
    <p v-if="status" class="help" role="status">{{ status }}</p>
    <p v-if="error" class="help danger-text" role="alert">{{ error }}</p>
    <template #footer>
      <button class="btn btn-outline btn-sm" type="button" :disabled="busy" @click="emit('close')">{{ u("cancel") }}</button>
      <button class="btn btn-destructive btn-sm" type="button" :disabled="!ready" @click="emit('confirm')"><Icon v-if="busy" name="loader" />{{ action }}</button>
    </template>
  </AppDialog>
</template>
