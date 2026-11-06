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
button:focus-visible {
  outline: 3px solid #1d5fbf;
  outline-offset: 3px;
}
</style>
