// Pinia shim to install a devtools hook early and re-export real Pinia (avoids devtools crash in Vitest)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
if (!(globalThis as any).__VUE_DEVTOOLS_GLOBAL_HOOK__) {
  const hook = { on() {}, off() {}, emit() {}, once() {} }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(globalThis as any).__VUE_DEVTOOLS_GLOBAL_HOOK__ = hook
  if (typeof window !== 'undefined') {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(window as any).__VUE_DEVTOOLS_GLOBAL_HOOK__ = hook
  }
}
// Import and re-export public Pinia API (avoid deep path for typings)
export * from 'pinia'
// Re-export testing helpers from the real package (installed via PR #10)
export { createTestingPinia } from '@pinia/testing'
