<script setup lang="ts">
import { reactive } from "vue";
import PassageSearch from "./PassageSearch.vue";
import BookQuestion from "./BookQuestion.vue";
import ConversationHistory from "./ConversationHistory.vue";
import type { Book } from "../api/libraryApi";
import ReadingProgress from "./ReadingProgress.vue";

defineProps<{ books: Book[]; loading: boolean; busy: boolean; error: string; model: string }>();
const searchAvailable = reactive<Record<string, boolean>>({});
const historyVersion = reactive<Record<string, number>>({});
defineEmits<{ retry: []; delete: [book: Book]; review: [book: Book] }>();
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
            {{ book.chapters_confirmed ? "Chapters confirmed" : "Chapter review needed" }}
          </p>
          <ReadingProgress
            v-if="book.chapters_confirmed"
            :book-id="book.id"
            @availability="searchAvailable[book.id] = $event"
          />
          <PassageSearch v-if="searchAvailable[book.id]" :book-id="book.id" />
          <BookQuestion
            v-if="searchAvailable[book.id]"
            :book-id="book.id"
            :model="model"
            @saved="historyVersion[book.id] = (historyVersion[book.id] ?? 0) + 1"
          />
          <ConversationHistory
            v-if="searchAvailable[book.id]"
            :book-id="book.id"
            :version="historyVersion[book.id] ?? 0"
          />
        </div>
        <div class="actions">
          <button
            class="review"
            type="button"
            :disabled="busy"
            :aria-label="`Review chapters for ${book.title}`"
            @click="$emit('review', book)"
          >
            Review chapters
          </button>
          <button
            class="delete"
            type="button"
            :disabled="busy"
            :aria-label="`Delete ${book.title}`"
            @click="$emit('delete', book)"
          >
            Delete
          </button>
        </div>
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
.actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.review {
  border: 0;
  background: transparent;
  text-decoration: underline;
  min-height: 44px;
  padding: 10px;
  white-space: nowrap;
}
.book-list {
  padding: 0;
  margin: 0;
  list-style: none;
}
.book-row {
  align-items: flex-start;
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
  .book-row {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }
  .actions {
    justify-content: flex-start;
    margin-left: -10px;
  }
}
</style>
