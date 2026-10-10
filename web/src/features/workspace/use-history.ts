import { computed, onBeforeUnmount, reactive, watch, type Ref } from "vue";
import { historyRevision, type WorkspaceModule } from "./state";
import { loadRecords, type HistoryRecord } from "./history-api";

function empty() {
  return {
    items: [] as HistoryRecord[],
    next: null as string | number | null,
    query: "",
    loaded: false,
    revision: -1,
    loading: false,
    error: false,
    scroll: 0,
  };
}
// Cache is local to the sidebar. Changing the signed-in identity remounts it,
// so another account cannot inherit this account's history.
export function useHistory(
  module: Ref<WorkspaceModule>,
  enabled: Ref<boolean>,
) {
  const pages = reactive({
    search: empty(),
    bibliometrics: empty(),
    reviews: empty(),
  });
  const page = computed(() => pages[module.value]);
  let controller: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let generation = 0;
  async function load(more = false) {
    controller?.abort();
    const token = ++generation,
      target = page.value,
      kind = module.value;
    const query = target.query,
      revision = historyRevision[kind];
    controller = new AbortController();
    target.loading = true;
    target.error = false;
    try {
      const result = await loadRecords(
        kind,
        query,
        more ? target.next : null,
        controller.signal,
      );
      if (token !== generation) return;
      target.items = more ? [...target.items, ...result.items] : result.items;
      target.next = result.next;
      target.loaded = true;
      target.revision = revision;
    } catch (error) {
      if (
        token === generation &&
        !(error instanceof Error && error.name === "AbortError")
      )
        target.error = true;
    } finally {
      if (token === generation) target.loading = false;
    }
  }
  watch(
    [module, enabled, () => historyRevision[module.value]],
    () => {
      clearTimeout(timer);
      controller?.abort();
      generation++;
      for (const value of Object.values(pages)) value.loading = false;
      if (
        enabled.value &&
        (!page.value.loaded ||
          page.value.revision !== historyRevision[module.value])
      )
        void load();
    },
    { immediate: true },
  );
  function search(value: string) {
    clearTimeout(timer);
    controller?.abort();
    generation++;
    page.value.query = value;
    page.value.loaded = false;
    page.value.items = [];
    page.value.next = null;
    page.value.loading = true;
    timer = setTimeout(() => {
      if (enabled.value) void load();
    }, 250);
  }
  onBeforeUnmount(() => {
    controller?.abort();
    clearTimeout(timer);
    generation++;
  });
  return { page, load, search };
}
