<script setup lang="ts">
import { requestErrors } from "./pages/library/api/apiFetch";
import LibraryPage from "./pages/library/ui/LibraryPage.vue";
</script>

<template>
  <LibraryPage />
  <div class="notifications" aria-label="Backend errors">
    <div v-for="message in requestErrors" :key="message" class="notification">
      <div role="alert">
        <strong>Request failed</strong>
        <p>{{ message }}</p>
      </div>
      <button
        type="button"
        aria-label="Dismiss error"
        @click="requestErrors = requestErrors.filter((item) => item !== message)"
      >
        ×
      </button>
    </div>
  </div>
</template>

<style>
.notifications {
  position: fixed;
  z-index: 100;
  right: 20px;
  bottom: 20px;
  width: min(380px, calc(100vw - 32px));
  max-height: 60dvh;
  overflow-y: auto;
  display: grid;
  gap: 8px;
}
.notification {
  display: flex;
  gap: 16px;
  align-items: start;
  justify-content: space-between;
  padding: 16px;
  border: 1px solid #dfb5ae;
  border-radius: 10px;
  background: #fffaf9;
  color: #652c26;
  box-shadow: 0 8px 24px #1b1b1b1a;
  overflow-wrap: anywhere;
}
.notification p {
  margin: 4px 0 0;
}
.notification button {
  flex: none;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  font-size: 24px;
  line-height: 1;
}
.notification button:hover {
  background: #f5e4e1;
}
@media (max-width: 700px) {
  .notifications {
    right: 16px;
    bottom: 16px;
  }
}
* {
  box-sizing: border-box;
}
body {
  margin: 0;
  background: #f4f3f1;
  color: #1b1b1b;
  font:
    16px/1.5 system-ui,
    sans-serif;
}
button {
  font: inherit;
  cursor: pointer;
}
button:disabled {
  cursor: wait;
  opacity: 0.55;
}
button:focus-visible,
select:focus-visible,
input:focus-visible,
textarea:focus-visible,
summary:focus-visible {
  outline: 3px solid #1d5fbf;
  outline-offset: 3px;
}
main.workspace select {
  appearance: none;
  min-width: 0;
  max-width: 100%;
  min-height: 44px;
  padding: 10px 40px 10px 12px;
  border: 1px solid #b8c7b9;
  border-radius: 8px;
  background: #fff
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16' fill='none'%3E%3Cpath d='m4 6 4 4 4-4' stroke='%23475d4e' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E")
    no-repeat right 12px center;
  color: #202521;
  font: inherit;
  text-overflow: ellipsis;
}
main.workspace select:disabled {
  color: #657168;
  background-color: #f3f5f1;
}
</style>
