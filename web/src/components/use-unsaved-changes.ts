import { onBeforeUnmount, onMounted, ref, type Ref } from "vue";
import { onBeforeRouteLeave, onBeforeRouteUpdate } from "vue-router";

/** Protect editing without persisting document content or credentials in storage. */
export function useUnsavedChanges(dirty: Ref<boolean>) {
  const pending = ref(false);
  let resolve: ((leave: boolean) => void) | undefined;
  function decide(leave: boolean) {
    pending.value = false;
    resolve?.(leave);
    resolve = undefined;
  }
  function confirmLeave(): boolean | Promise<boolean> {
    if (!dirty.value) return true;
    resolve?.(false);
    pending.value = true;
    return new Promise<boolean>((done) => {
      resolve = done;
    });
  }
  function unload(event: BeforeUnloadEvent) {
    if (dirty.value) {
      event.preventDefault();
      event.returnValue = "";
    }
  }
  onBeforeRouteLeave(confirmLeave);
  onBeforeRouteUpdate((to, from) => to.path === from.path || confirmLeave());
  onMounted(() => window.addEventListener("beforeunload", unload));
  onBeforeUnmount(() => {
    window.removeEventListener("beforeunload", unload);
    decide(false);
  });
  return { pending, decide, confirmLeave };
}
