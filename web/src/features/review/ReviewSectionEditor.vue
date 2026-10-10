<script setup lang="ts">
import Icon from "../../components/Icon.vue";
import { useUi } from "../../locales/ui";
import { computed, ref } from "vue";
import { useLocale } from "../../locales";
import { reviewApi, type Body, type Review, type Section } from "./api";
import ReviewDialog from "../../components/AppDialog.vue";
import { useUnsavedChanges } from "../../components/use-unsaved-changes";
import UnsavedChangesDialog from "../../components/UnsavedChangesDialog.vue";
const props = defineProps<{
  review: Review;
  section: Section;
  busy: boolean;
  error: string;
}>();
const emit = defineEmits<{
  close: [];
  save: [operation: () => Promise<unknown>];
}>();
const { t } = useLocale();
const u = useUi();
const draft = ref<Body>(JSON.parse(JSON.stringify(props.section.body)));
const original = ref(JSON.stringify(draft.value));
const dirty = computed(() => JSON.stringify(draft.value) !== original.value);
const { pending, decide, confirmLeave } = useUnsavedChanges(dirty);
async function close() {
  if (!props.busy && (await confirmLeave())) emit("close");
}
const title = computed(
  () =>
    props.review.content.outline?.sections.find(
      (s) => s.id === props.section.section_id,
    )?.title || "",
);
const version = props.review.version,
  revision = props.section.revision;
const available = computed(() => {
  const paperIds = new Set(
    props.review.content.outline?.sections.find(
      (s) => s.id === props.section.section_id,
    )?.paper_ids,
  );
  return (props.review.content.cards || [])
    .filter((c) => paperIds.has(c.paper_id))
    .flatMap((c) => c.evidence);
});
function save() {
  emit("save", async () => {
    await reviewApi.section(props.review.id, props.section.section_id, {
      expected_version: version,
      expected_revision: revision,
      body: draft.value,
    });
    original.value = JSON.stringify(draft.value);
    emit("close");
  });
}
</script>
<template>
  <ReviewDialog :title="`${u('editSection')} · ${title}`" :description="t('reviewEditHint')" :busy="busy" size="lg" @close="close">
    <form id="section-edit-form" class="stack" style="gap: 12px" @submit.prevent="save">
      <p v-if="error" class="help danger-text" role="alert">{{ t(error) }}</p>
      <fieldset v-for="(paragraph, index) in draft.paragraphs" :key="index" class="para" style="margin: 0" :disabled="busy">
        <div class="row" style="justify-content: space-between">
          <label class="xs medium muted" :for="`paragraph-${index}`">{{ u("paragraphN", { n: index + 1 }) }}</label>
          <button class="btn btn-ghost btn-icon btn-xs" type="button" style="width: 24px; height: 24px" :aria-label="u('removeParagraph', { n: index + 1 })" :disabled="draft.paragraphs.length === 1" @click="draft.paragraphs.splice(index, 1)"><Icon name="x" size="sm" /></button>
        </div>
        <textarea :id="`paragraph-${index}`" v-model="paragraph.text" class="input textarea" rows="5" required maxlength="6000"></textarea>
        <details>
          <summary class="row sm" style="cursor: pointer; gap: 6px"><Icon name="chevron-right" class="muted" />{{ u("citationsN", { n: paragraph.evidence_ids.length }) }}</summary>
          <div class="stack" style="gap: 8px; margin-top: 8px; max-height: 240px; overflow-y: auto">
            <label v-for="evidence in available" :key="evidence.id" class="cb" style="align-items: flex-start">
              <input v-model="paragraph.evidence_ids" type="checkbox" :value="evidence.id" /><span class="box" style="margin-top: 2px"><Icon name="check" /></span>
              <span class="stack" style="gap: 2px"><span class="sm medium">{{ review.content.papers.find((p) => p.id === evidence.paper_id)?.title }}</span><span class="quote">{{ evidence.quote }}</span></span>
            </label>
          </div>
        </details>
      </fieldset>
      <p v-if="draft.paragraphs.some((p) => !p.evidence_ids.length)" class="help" role="status">{{ u("needEvidence") }}</p>
    </form>
    <template #footer>
      <button class="btn btn-ghost btn-sm" type="button" style="margin-right: auto" :disabled="busy || draft.paragraphs.length >= 40" @click="draft.paragraphs.push({ text: '', evidence_ids: [] })"><Icon name="plus" />{{ u("addParagraph") }}</button>
      <button class="btn btn-outline btn-sm" type="button" :disabled="busy" @click="close">{{ u("cancel") }}</button>
      <button class="btn btn-sm" type="submit" form="section-edit-form" :disabled="busy || draft.paragraphs.some((p) => !p.evidence_ids.length)">{{ u("save") }}</button>
    </template>
  </ReviewDialog>
  <UnsavedChangesDialog :open="pending" @decide="decide" />
</template>
