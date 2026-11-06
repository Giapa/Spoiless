<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useLibrary } from "../model/useLibrary";
import AddBookButton from "./AddBookButton.vue";
import BookList from "./BookList.vue";
import SemanticModelSetup from "./SemanticModelSetup.vue";
import ChatGPTConnection from "./ChatGPTConnection.vue";
import ChatGPTModelPicker from "./ChatGPTModelPicker.vue";

const selectedModel = ref("");
const accountVersion = ref(0);
const selectedBookId = ref("");
const { books, loading, busy, error, notice, loadBooks, addBook, removeBook } = useLibrary();
const selectedBook = computed(() => books.value.find((book) => book.id === selectedBookId.value));
watch(
  () => books.value.map((book) => book.id),
  (ids) => {
    if (!ids.includes(selectedBookId.value)) selectedBookId.value = ids[0] ?? "";
  },
  { immediate: true },
);
</script>

<template>
  <main class="workspace">
    <aside class="sidebar" aria-label="Library and settings">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">S</span>
        <div>
          <h1>Spoiless</h1>
          <p>Your reading companion</p>
        </div>
      </div>
      <label for="book-select">Book</label>
      <select id="book-select" v-model="selectedBookId" :disabled="!books.length">
        <option v-if="!books.length" value="">No books yet</option>
        <option v-for="book in books" :key="book.id" :value="book.id">{{ book.title }}</option>
      </select>
      <AddBookButton :disabled="busy || loading" :busy="busy" @select="addBook" />
      <p class="hint">EPUB files stay on this device. Maximum 25 MB.</p>
      <p v-if="error" class="message error" role="alert">
        {{ error }} <button type="button" @click="loadBooks">Retry</button>
      </p>
      <p v-if="notice" class="message" role="status">{{ notice }}</p>
      <details class="settings">
        <summary>Account and model</summary>
        <ChatGPTConnection @account-changing="accountVersion++" />
        <ChatGPTModelPicker v-model="selectedModel" :account-version="accountVersion" />
      </details>
      <details class="settings">
        <summary>Local search settings</summary>
        <SemanticModelSetup />
      </details>
    </aside>
    <BookList
      :key="selectedBook?.id"
      :book="selectedBook"
      :loading="loading"
      :busy="busy"
      :model="selectedModel"
      @delete="removeBook"
    />
  </main>
</template>

<style scoped>
.workspace {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 290px minmax(0, 1fr);
  background: #faf9f6;
  color: #202521;
}
.sidebar {
  padding: 28px 20px;
  background: #eef1ea;
  border-right: 1px solid #dce1d8;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 12px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 24px;
}
.brand-mark {
  display: grid;
  place-items: center;
  height: 38px;
  width: 38px;
  border-radius: 11px;
  color: #fff;
  background: #315b45;
  font-weight: 700;
  font-size: 20px;
}
h1,
p {
  margin: 0;
}
h1 {
  font-size: 18px;
  letter-spacing: -0.02em;
}
.brand p,
.hint,
.message {
  font-size: 13px;
  line-height: 1.5;
  color: #536157;
}
label {
  font-size: 13px;
  font-weight: 650;
}
select {
  width: 100%;
  min-height: 44px;
  padding: 8px 10px;
  border: 1px solid #c7d0c6;
  border-radius: 8px;
  background: white;
  font: inherit;
}
.settings {
  border-top: 1px solid #d6ded4;
  padding-top: 12px;
}
summary {
  min-height: 36px;
  cursor: pointer;
  font-weight: 600;
  font-size: 14px;
}
.error {
  color: #9c2929;
}
button {
  font: inherit;
}
@media (max-width: 700px) {
  .workspace {
    display: block;
  }
  .sidebar {
    padding: 18px 16px;
    border-right: 0;
    border-bottom: 1px solid #dce1d8;
  }
  .brand {
    margin-bottom: 4px;
  }
}
</style>
