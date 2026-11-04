<script setup lang="ts">
import { useLibrary } from "../model/useLibrary";
import AddBookButton from "./AddBookButton.vue";
import BookList from "./BookList.vue";
import SemanticModelSetup from "./SemanticModelSetup.vue";

defineEmits<{ review: [book: { id: string; title: string }] }>();
const { books, loading, busy, error, notice, loadBooks, addBook, removeBook } = useLibrary();
</script>

<template>
  <main>
    <div class="intro">
      <div>
        <h1>Your library</h1>
        <p>Books stay on this device.</p>
      </div>
      <AddBookButton :disabled="busy || loading" :busy="busy" @select="addBook" />
    </div>
    <p class="hint">Unencrypted EPUB files, up to 25 MB.</p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="notice" class="message" role="status">{{ notice }}</p>
    <BookList
      :books="books"
      :loading="loading"
      :busy="busy"
      :error="error"
      @retry="loadBooks"
      @delete="removeBook"
      @review="$emit('review', $event)"
    />
    <SemanticModelSetup />
    <p class="footnote">Recaps and questions are coming in later tasks.</p>
  </main>
</template>

<style scoped>
main {
  max-width: 1064px;
  margin: 60px auto;
  padding: 0 24px;
}
.intro {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
}
h1,
p {
  margin: 0;
}
h1 {
  font-size: 30px;
  line-height: 1.2;
  font-weight: 650;
}
.intro p,
.hint,
.footnote {
  color: #555;
}
.intro p {
  margin-top: 6px;
}
.hint {
  margin: 16px 0 28px;
  font-size: 14px;
}
.message {
  margin-bottom: 20px;
  padding: 12px 16px;
  background: #fff;
  border-left: 3px solid #555;
}
.error {
  border-color: #ac2525;
}
.footnote {
  font-size: 14px;
  margin-top: 24px;
}
@media (max-width: 600px) {
  main {
    margin: 36px auto;
    padding: 0 16px;
  }
  h1 {
    font-size: 24px;
  }
  .intro {
    align-items: flex-start;
  }
}
</style>
