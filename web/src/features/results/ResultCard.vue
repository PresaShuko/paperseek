<script setup lang="ts">
import { computed, ref } from "vue";
import type { PaperResult } from "../../api/types";
import AppDialog from "../../components/AppDialog.vue";
import Icon from "../../components/Icon.vue";
import UiMenu from "../../components/UiMenu.vue";
import { useLocale } from "../../locales";
import { useUi } from "../../locales/ui";

const props = defineProps<{ paper: PaperResult; identity: string; selected: boolean; expanded: ReadonlySet<string> }>();
const emit = defineEmits<{ select: []; expand: [key: string] }>();
const { sourceName, t } = useLocale();
const u = useUi();
const details = ref(false);
const score = computed(() => {
  const value = props.paper.score ?? props.paper.relevance_score;
  return value === null || value === undefined ? null : Number(value);
});
const scoreClass = computed(() => (score.value === null ? "badge-outline muted" : score.value >= 8 ? "" : score.value >= 5 ? "badge-secondary" : "badge-outline"));
const authors = computed(() => props.paper.authors_text || props.paper.authors?.filter(Boolean).join(", ") || t("unknownAuthors"));
const year = computed(() => props.paper.year ?? props.paper.publish_year);
const venue = computed(() => props.paper.venue || props.paper.source || "");
const citations = computed(() => props.paper.citation_count ?? props.paper.citations);
const reasoning = computed(() => props.paper.reasoning || props.paper.relevance_reason || "");
const open = computed(() => props.expanded.has(`${props.identity}:abstract`));
const keywords = computed(() => (Array.isArray(props.paper.keywords) ? props.paper.keywords.join("; ") : props.paper.keywords || ""));
const type = computed(() => (props.paper.document_types?.length ? props.paper.document_types.join("; ") : props.paper.publication_type || ""));
</script>

<template>
  <article class="card paper" data-testid="result-card" :class="{ sel: selected }">
    <label class="cb" style="margin-top: 3px" :aria-label="`${u('select')}: ${paper.title}`"><input type="checkbox" :checked="selected" @change="emit('select')" /><span class="box"><Icon name="check" /></span></label>
    <div class="stack" style="gap: 4px; min-width: 0">
      <a v-if="paper.url" class="paper-title" :href="paper.url" target="_blank" rel="noopener">{{ paper.title }}</a>
      <span v-else class="paper-title">{{ paper.title }}</span>
      <p class="sm muted truncate" :title="authors">{{ authors }}<template v-if="venue || year"> · {{ [venue, year].filter(Boolean).join(" ") }}</template></p>
    </div>
    <UiMenu :label="u('paperMore')" align="end">
      <template #trigger><Icon name="ellipsis" /></template>
      <a v-if="paper.url" class="opt" role="menuitem" data-menu-item :href="paper.url" target="_blank" rel="noopener"><Icon name="arrow-up-right" />{{ u("openRecord") }}</a>
      <a v-if="paper.pdf_url" class="opt" role="menuitem" data-menu-item :href="paper.pdf_url" target="_blank" rel="noopener"><Icon name="download" />{{ u("openPdf") }}</a>
      <button class="opt" role="menuitem" data-menu-item type="button" @click="details = true"><Icon name="file-text" />{{ u("details") }}</button>
    </UiMenu>
    <div class="body">
      <p v-if="paper.abstract" class="abstract" :class="{ 'clamp-2': !open }" style="cursor: pointer" :title="open ? undefined : t('expandAll')" @click="emit('expand', `${identity}:abstract`)">{{ paper.abstract }}</p>
      <p v-else class="abstract">{{ u("noAbstract") }}</p>
      <p v-if="reasoning" class="sm" style="color: #404040"><span class="medium" style="color: var(--foreground)">{{ u("reasoning") }} · </span>{{ reasoning }}</p>
      <div class="row" style="gap: 6px">
        <span class="badge" :class="scoreClass" data-testid="result-score">{{ score === null ? u("unscored") : `${score}/10` }}</span>
        <a v-if="paper.doi" class="badge badge-outline" :href="`https://doi.org/${paper.doi}`" target="_blank" rel="noopener">DOI</a>
        <a v-if="paper.pdf_url" class="badge badge-secondary" :href="paper.pdf_url" target="_blank" rel="noopener"><Icon name="download" />PDF</a>
        <span v-if="citations != null" class="xs muted num end">{{ u("citations", { n: Number(citations).toLocaleString() }) }}</span>
      </div>
    </div>
    <AppDialog v-if="details" :title="paper.title || ''" size="lg" @close="details = false">
      <dl class="kv" style="grid-template-columns: auto minmax(0, 1fr)">
        <dt>{{ u("authors") }}</dt><dd style="text-align: left">{{ authors }}</dd>
        <template v-if="year"><dt>{{ u("year") }}</dt><dd style="text-align: left">{{ year }}</dd></template>
        <template v-if="venue"><dt>{{ u("venue") }}</dt><dd style="text-align: left">{{ venue }}</dd></template>
        <template v-if="type"><dt>{{ u("type") }}</dt><dd style="text-align: left">{{ type }}</dd></template>
        <template v-if="paper.doi"><dt>DOI</dt><dd style="text-align: left"><a class="link" :href="`https://doi.org/${paper.doi}`" target="_blank" rel="noopener">{{ paper.doi }}</a></dd></template>
        <template v-if="keywords"><dt>{{ u("keywords") }}</dt><dd style="text-align: left">{{ keywords }}</dd></template>
        <template v-if="paper.provider"><dt>{{ u("provider") }}</dt><dd style="text-align: left">{{ sourceName(paper.provider, paper.provider) }}</dd></template>
        <template v-if="paper.rank"><dt>{{ t("rankLabel") }}</dt><dd style="text-align: left">{{ paper.rank }}</dd></template>
      </dl>
      <p v-if="paper.abstract" class="abstract">{{ paper.abstract }}</p>
    </AppDialog>
  </article>
</template>
