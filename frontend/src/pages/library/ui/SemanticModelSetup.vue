<script setup lang="ts">
import { onMounted, ref } from "vue";
import { z } from "zod";

const ready = ref<boolean | null>(null);
const busy = ref(false);
const error = ref("");
const statusSchema = z.object({ ready: z.boolean() });
async function load() {
  error.value = "";
  try {
    const response = await fetch("/api/semantic-model");
    if (!response.ok) throw new Error();
    ready.value = statusSchema.parse(await response.json()).ready;
  } catch {
    error.value = "Could not check model setup.";
  }
}
async function download() {
  busy.value = true;
  error.value = "";
  try {
    const response = await fetch("/api/semantic-model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ consent: true }),
    });
    if (!response.ok) throw new Error();
    ready.value = statusSchema.parse(await response.json()).ready;
  } catch {
    error.value = "Model setup failed. Check your connection and try again.";
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>

<template>
  <section class="model" aria-labelledby="model-heading">
    <h2 id="model-heading">Semantic search setup</h2>
    <p>Semantic search will find passages by meaning. The English model runs on this device.</p>
    <p v-if="ready">Model downloaded. You can search by meaning in a book with saved progress.</p>
    <template v-else-if="ready === false">
      <p>The one-time model download is approximately 90 MB. No book text is sent.</p>
      <button type="button" :disabled="busy" @click="download">
        {{ busy ? "Downloading model…" : "Download model" }}
      </button>
    </template>
    <p v-else-if="!error" role="status">Checking model setup…</p>
    <p v-if="error" role="alert">{{ error }} <button type="button" @click="load">Retry</button></p>
  </section>
</template>

<style scoped>
.model {
  margin-top: 12px;
  padding: 16px;
  background: #fff;
  border: 1px solid #e2e2e2;
  border-radius: 8px;
}
h2 {
  margin: 0;
  font-size: 17px;
}
p {
  margin: 8px 0;
  color: #555;
  font-size: 14px;
}
button {
  max-width: 100%;
  font: inherit;
  min-height: 44px;
  padding: 8px 16px;
  border: 1px solid #aaa;
  border-radius: 6px;
  background: #fff;
}
@media (max-width: 600px) {
  .model {
    padding: 16px;
  }
}
</style>
