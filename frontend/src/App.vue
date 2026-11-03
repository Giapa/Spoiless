<script setup lang="ts">
import { onMounted, ref } from "vue";
import { z } from "zod";

const state = ref("Checking connection…");

onMounted(async () => {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error("Backend unavailable");
    z.object({ status: z.literal("ok") }).parse(await response.json());
    state.value = "Local backend connected.";
  } catch {
    state.value = "Local backend unavailable. Start the backend and refresh.";
  }
});
</script>

<template>
  <main>
    <h1>Spoiless</h1>
    <p>A reading companion that respects your progress.</p>
    <p role="status">{{ state }}</p>
    <p>Book upload and questions are coming in later tasks.</p>
  </main>
</template>

<style>
body {
  margin: 0;
  font-family: system-ui, sans-serif;
  color: #202820;
  background: #f4f6f2;
}
main {
  max-width: 44rem;
  margin: 5rem auto;
  padding: 0 1.5rem;
}
h1 {
  font-size: 2rem;
}
p {
  line-height: 1.6;
}
</style>
