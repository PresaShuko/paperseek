<script setup lang="ts">
import AppDialog from "./AppDialog.vue";
import { useLocale } from "../locales";
defineProps<{ open: boolean }>();
const emit = defineEmits<{ decide: [leave: boolean] }>();
const { language } = useLocale();
</script>
<template>
  <AppDialog
    v-if="open"
    :title="language === 'zh' ? '保留未保存的修改？' : 'Unsaved changes'"
    :description="language === 'zh' ? '离开会丢弃当前修改。可以返回继续编辑并保存。' : 'Leaving will discard your changes. Return to the editor to save them.'"
    @close="emit('decide', false)"
  >
    <template #footer>
      <button class="btn btn-outline btn-sm" type="button" @click="emit('decide', true)">{{ language === "zh" ? "放弃修改" : "Discard changes" }}</button>
      <button class="btn btn-sm" type="button" @click="emit('decide', false)">{{ language === "zh" ? "继续编辑" : "Keep editing" }}</button>
    </template>
  </AppDialog>
</template>
