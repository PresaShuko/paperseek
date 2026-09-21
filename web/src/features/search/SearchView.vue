<script setup lang="ts">
// Thin wrapper kept for the Hosted alias imports: props, emits and slots are
// forwarded unchanged to the shared workbench (edit mode).
import { ref } from "vue";

import type { DiagnosticSubmission, RunDetail, SourceDescriptor } from "../../api/types";
import SearchWorkspace from "./SearchWorkspace.vue";

withDefaults(defineProps<{
  submissionEnabled?: boolean;
  service?: DiagnosticSubmission['service'];
  modelSettings?: Pick<DiagnosticSubmission, 'llm' | 'retrieval'>;
  sourceOptions?: SourceDescriptor[];
  credentialHelp?: string;
}>(), { submissionEnabled: true });
const emit = defineEmits<{ submitted: [run: RunDetail] }>();

const workspace = ref<InstanceType<typeof SearchWorkspace> | null>(null);
defineExpose({ clearCredentials: () => workspace.value?.clearCredentials() });
</script>

<template>
  <SearchWorkspace
    ref="workspace"
    mode="edit"
    :submission-enabled="submissionEnabled"
    :service="service"
    :model-settings="modelSettings"
    :source-options="sourceOptions"
    :credential-help="credentialHelp"
    @submitted="emit('submitted', $event)"
  >
    <template v-if="$slots['service-mode']" #service-mode><slot name="service-mode" /></template>
    <template v-if="$slots['source-note']" #source-note="scope"><slot name="source-note" v-bind="scope" /></template>
    <template v-if="$slots['submit-error']" #submit-error="scope"><slot name="submit-error" v-bind="scope" /></template>
    <template v-if="$slots['log-export']" #log-export="scope"><slot name="log-export" v-bind="scope" /></template>
  </SearchWorkspace>
</template>
