<script setup lang="ts">
// Account row at the bottom of the sidebar (shadcn NavUser) and its menu.
import Icon from "../../components/Icon.vue";
import UiMenu from "../../components/UiMenu.vue";
import { useLocale } from "../../locales";
import { useUi } from "../../locales/ui";

defineProps<{
  serviceMode?: "paperseek" | "byok";
  serviceDisabled?: boolean;
  collapsed?: boolean;
  displayName?: string;
  displayDetail?: string;
  initials?: string;
}>();
const emit = defineEmits<{ mode: [value: "paperseek" | "byok"]; opened: [] }>();
const { language, setLanguage } = useLocale();
const u = useUi();
</script>

<template>
  <UiMenu :label="u('account')" trigger-class="user" side="top" align="start" :min-width="240" style="display: flex; width: 100%" @opened="emit('opened')">
    <template #trigger>
      <span class="avatar">{{ initials || "PS" }}</span>
      <span class="stack grow" style="line-height: 1.25"><span class="sm medium truncate">{{ displayName || "PaperSeek" }}</span><span class="xs muted truncate">{{ displayDetail || u("local") }}</span></span>
      <Icon name="ellipsis" />
    </template>
    <div class="row" style="gap: 8px; padding: 6px 8px; flex-wrap: nowrap">
      <span class="avatar">{{ initials || "PS" }}</span>
      <span class="stack grow" style="line-height: 1.25; min-width: 0"><slot name="identity"><span class="sm medium">{{ displayName || "PaperSeek" }}</span><span class="xs muted">{{ displayDetail || u("local") }}</span></slot></span>
    </div>
    <slot name="account" />
    <div class="opt-sep" role="separator"></div>
    <template v-if="serviceMode">
      <div class="opt-label">PaperSeek / BYOK</div>
      <button
        v-for="option in ['paperseek', 'byok'] as const"
        :key="option"
        class="opt"
        role="menuitemradio"
        data-menu-item
        :aria-checked="serviceMode === option"
        :disabled="serviceDisabled"
        @click="emit('mode', option)"
      >{{ option === "paperseek" ? "PaperSeek" : "BYOK" }}<Icon v-if="serviceMode === option" name="check" class="check" /></button>
      <div class="opt-sep" role="separator"></div>
    </template>
    <div class="opt-label">{{ u("language") }}</div>
    <button
      v-for="option in ['zh', 'en'] as const"
      :key="option"
      class="opt"
      role="menuitemradio"
      data-menu-item
      :aria-checked="language === option"
      @click="setLanguage(option)"
    >{{ option === "zh" ? "简体中文" : "English" }}<Icon v-if="language === option" name="check" class="check" /></button>
    <div class="opt-sep" role="separator"></div>
    <RouterLink class="opt" role="menuitem" data-menu-item to="/settings/models"><Icon name="settings" />{{ u("settings") }}</RouterLink>
    <a class="opt" role="menuitem" data-menu-item href="https://docs.paperseek.app/" target="_blank" rel="noopener"><Icon name="circle-help" />{{ u("docs") }}</a>
    <slot name="session" />
  </UiMenu>
</template>
