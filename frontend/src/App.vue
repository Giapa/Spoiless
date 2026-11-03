<script setup lang="ts">
import LibraryPage from "./pages/library/ui/LibraryPage.vue";
import ChapterReviewPage from "./pages/chapter-review/ui/ChapterReviewPage.vue";
import { ref } from "vue";

const selectedBook = ref<{ id: string; title: string } | null>(null);
</script>

<template>
  <header class="topbar">
    <div class="topbar-inner">
      <span class="mark" aria-hidden="true">S</span><span>Spoiless</span>
    </div>
  </header>
  <LibraryPage v-if="!selectedBook" @review="selectedBook = $event" />
  <ChapterReviewPage v-else :book="selectedBook" @back="selectedBook = null" />
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
.topbar {
  background: #fff;
  border-bottom: 1px solid #e6e6e6;
}
.topbar-inner {
  max-width: 1064px;
  margin: auto;
  padding: 18px 24px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 650;
}
.mark {
  display: inline-grid;
  place-items: center;
  border: 1px solid #333;
  width: 29px;
  height: 29px;
  font-family: Georgia, serif;
}
@media (max-width: 600px) {
  .topbar-inner {
    padding-inline: 16px;
  }
}
</style>
