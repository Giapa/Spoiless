import { onMounted, ref } from "vue";
import { deleteBook, fetchBooks, importBook, type Book } from "../api/libraryApi";

export function useLibrary() {
  const books = ref<Book[]>([]);
  const loading = ref(true);
  const busy = ref(false);
  const error = ref("");
  const notice = ref("");

  async function loadBooks() {
    loading.value = true;
    error.value = "";
    try {
      books.value = await fetchBooks();
    } catch {
      error.value = "Could not load your library. Make sure the local backend is running.";
    } finally {
      loading.value = false;
    }
  }

  async function addBook(file: File) {
    error.value = "";
    notice.value = "";
    if (!file.name.toLowerCase().endsWith(".epub")) {
      error.value = "Choose an EPUB file.";
      return;
    }
    if (file.size > 25 * 1024 * 1024) {
      error.value = "Choose a file smaller than 25 MB.";
      return;
    }
    busy.value = true;
    try {
      const book = await importBook(file);
      books.value.unshift(book);
      notice.value = `Added ${book.title}.`;
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "Could not add the book.";
    } finally {
      busy.value = false;
    }
  }

  async function removeBook(book: Book) {
    if (!window.confirm(`Delete “${book.title}” from this device?`)) return;
    busy.value = true;
    error.value = "";
    notice.value = "";
    try {
      await deleteBook(book.id);
      books.value = books.value.filter((item) => item.id !== book.id);
      notice.value = `Deleted ${book.title}.`;
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "Could not delete the book.";
    } finally {
      busy.value = false;
    }
  }

  onMounted(loadBooks);
  return { books, loading, busy, error, notice, loadBooks, addBook, removeBook };
}
