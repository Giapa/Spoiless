<script setup lang="ts">
import type { Book } from "../api/libraryApi";

defineProps<{ books: Book[]; loading: boolean; busy: boolean; error: string }>();
defineEmits<{ retry: []; delete: [book: Book] }>();
</script>

<template>
  <section aria-labelledby="books-heading" class="library">
    <div class="section-heading">
      <h2 id="books-heading">Books</h2>
      <span v-if="!loading && !error">{{ books.length }}</span>
    </div>
    <p v-if="loading" class="empty" role="status">Loading your library…</p>
    <div v-else-if="books.length === 0" class="empty">
      <p v-if="!error">Your library is empty. Add an EPUB to get started.</p>
      <button v-else type="button" class="secondary" @click="$emit('retry')">Try again</button>
    </div>
    <ul v-else class="book-list">
      <li v-for="book in books" :key="book.id" class="book-row">
        <div class="book-info">
          <h3>{{ book.title }}</h3>
          <p>
            {{ book.section_count }} {{ book.section_count === 1 ? "section" : "sections" }} ·
            Chapter review not available yet
          </p>
        </div>
        <button
          class="delete"
          type="button"
          :disabled="busy"
          :aria-label="`Delete ${book.title}`"
          @click="$emit('delete', book)"
        >
          Delete
        </button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.library {
  background: #fff;
  border: 1px solid #e2e2e2;
  border-radius: 8px;
}
.section-heading,
.book-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
}
.section-heading {
  padding: 20px 24px;
  border-bottom: 1px solid #eee;
}
h2,
h3,
p {
  margin: 0;
}
h2 {
  font-size: 17px;
  font-weight: 650;
}
.section-heading span,
.empty,
.book-info p {
  color: #555;
}
.empty {
  min-height: 140px;
  display: flex;
  align-items: center;
  padding: 24px;
}
.secondary,
.delete {
  border: 0;
  border-radius: 6px;
  padding: 10px 16px;
  min-height: 44px;
}
.secondary {
  color: #171717;
  background: #e8e8e8;
}
.delete {
  color: #343434;
  background: transparent;
}
.delete:hover {
  background: #eee;
}
.book-list {
  padding: 0;
  margin: 0;
  list-style: none;
}
.book-row {
  min-height: 88px;
  padding: 16px 24px;
}
.book-row + .book-row {
  border-top: 1px solid #eee;
}
.book-info {
  min-width: 0;
}
h3 {
  overflow-wrap: anywhere;
  font-size: 16px;
  font-weight: 600;
}
.book-info p {
  font-size: 14px;
  margin-top: 3px;
}
@media (max-width: 600px) {
  .section-heading,
  .book-row {
    padding-inline: 16px;
  }
}
</style>
