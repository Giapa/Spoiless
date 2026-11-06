<script setup lang="ts">
import LibraryPage from "./pages/library/ui/LibraryPage.vue";
</script>

<template>
  <LibraryPage />
</template>

<style>
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
