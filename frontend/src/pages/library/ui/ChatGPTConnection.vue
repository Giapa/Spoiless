<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from "vue";
import { z } from "zod";

const emit = defineEmits<{ accountChanging: [] }>();

const stateSchema = z.object({
  status: z.enum([
    "idle",
    "saved",
    "pending",
    "processing",
    "connected",
    "denied",
    "failed",
    "expired",
    "cancelled",
  ]),
  email: z.string().nullable(),
  plan_usage_enabled: z.boolean().nullable(),
});
type State = z.infer<typeof stateSchema>;
const state = ref<State | null>(null);
const error = ref("");
const revocationUnconfirmed = ref(false);
const busy = ref(false);
const noticeDialog = ref<HTMLDialogElement | null>(null);
const noticeAccount = ref("");
const selectedAccount = ref("");
const accounts = ref<{ id: string; email: string | null; active: boolean }[]>([]);
const accountSchema = z.array(
  z.object({ id: z.string(), email: z.string().nullable(), active: z.boolean() }),
);
async function showPlanNotice() {
  if (state.value?.status !== "connected" || !state.value.plan_usage_enabled) return;
  const active = accounts.value.find((account) => account.active);
  if (!active) return;
  try {
    if (localStorage.getItem(`spoiless-plan-notice:${active.id}`)) return;
  } catch {
    /* Show the notice even if browser storage is unavailable. */
  }
  noticeAccount.value = active.id;
  await nextTick();
  noticeDialog.value?.showModal();
}
function dismissPlanNotice() {
  try {
    localStorage.setItem(`spoiless-plan-notice:${noticeAccount.value}`, "1");
  } catch {
    /* Storage may be unavailable. */
  }
  noticeDialog.value?.close();
  noticeAccount.value = "";
}
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
let generation = 0;

async function request(path: string, action = false, accountId?: string): Promise<State> {
  const response = await fetch(
    path,
    action
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Spoiless-Action": "1" },
          body: JSON.stringify({ confirm: true, ...(accountId ? { account_id: accountId } : {}) }),
        }
      : undefined,
  );
  if (!response.ok) {
    const result = z
      .object({ detail: z.string() })
      .safeParse(await response.json().catch(() => null));
    throw new Error(result.success ? result.data.detail : "The request could not be completed.");
  }
  return stateSchema.parse(await response.json());
}
async function load() {
  const current = ++generation;
  try {
    const latest = await request("/api/chatgpt/sign-in");
    if (current !== generation || disposed) return;
    if (["idle", "saved", "connected"].includes(latest.status)) {
      const response = await fetch("/api/chatgpt/accounts");
      if (!response.ok) throw new Error();
      const saved = accountSchema.parse(await response.json());
      if (current !== generation || disposed) return;
      accounts.value = saved;
      selectedAccount.value = saved.find((account) => account.active)?.id ?? "";
    }
    state.value = latest;
    error.value = "";
    await showPlanNotice();
    if (!disposed && ["pending", "processing"].includes(state.value.status))
      timer = setTimeout(load, 1000);
  } catch {
    if (current === generation && !disposed)
      error.value = "Could not check the ChatGPT connection. Try again.";
  }
}
async function act(path: string) {
  if (path === "/api/chatgpt/sign-in") emit("accountChanging");
  generation++;
  busy.value = true;
  clearTimeout(timer);
  try {
    const accountId =
      path === "/api/chatgpt/sign-in" ? selectedAccount.value || undefined : undefined;
    state.value = await request(path, true, accountId);
    error.value = "";
    await showPlanNotice();
    if (!disposed && ["pending", "processing"].includes(state.value.status))
      timer = setTimeout(load, 1000);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "The request could not be completed.";
  } finally {
    busy.value = false;
  }
}
async function signOut() {
  emit("accountChanging");
  generation++;
  busy.value = true;
  clearTimeout(timer);
  try {
    const response = await fetch("/api/chatgpt/sign-out", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Spoiless-Action": "1" },
      body: JSON.stringify({ confirm: true }),
    });
    if (!response.ok) {
      const result = z
        .object({ detail: z.string() })
        .safeParse(await response.json().catch(() => null));
      throw new Error(result.success ? result.data.detail : "Sign-out failed. Try again.");
    }
    const result = z.object({ revocation_confirmed: z.boolean() }).parse(await response.json());
    revocationUnconfirmed.value = !result.revocation_confirmed;
    state.value = { status: "idle", email: null, plan_usage_enabled: null };
    accounts.value = accounts.value.map((account) => ({ ...account, active: false }));
    selectedAccount.value = "";
    error.value = "";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Sign-out failed. Try again.";
  } finally {
    busy.value = false;
  }
}

onMounted(load);
onUnmounted(() => {
  disposed = true;
  clearTimeout(timer);
});
</script>

<template>
  <section class="connection" aria-labelledby="chatgpt-heading">
    <h2 id="chatgpt-heading">ChatGPT connection</h2>
    <p>Eligible AI requests can use your ChatGPT plan.</p>
    <p v-if="state?.status === 'pending' || state?.status === 'processing'" role="status">
      Complete sign-in in your browser.
    </p>
    <div
      v-if="
        accounts.length &&
        (state?.status === 'idle' || state?.status === 'saved' || state?.status === 'connected')
      "
      class="account-choice"
    >
      <label for="chatgpt-account">Saved ChatGPT account</label>
      <select id="chatgpt-account" v-model="selectedAccount" :disabled="busy">
        <option v-for="(account, index) in accounts" :key="account.id" :value="account.id">
          Account {{ index + 1 }}{{ account.email ? ` · ${account.email}` : ""
          }}{{ account.active ? " (selected)" : "" }}
        </option>
        <option value="">Use a different account</option>
      </select>
    </div>
    <p v-if="state?.status === 'saved'" role="status">
      Saved account{{ state.email ? `: ${state.email}` : "" }}. Sign in again to connect.
    </p>
    <p v-if="state?.status === 'connected'" role="status">
      Connected{{ state.email ? ` as ${state.email}` : "" }}.
    </p>
    <p v-if="state?.status === 'connected' && !state.plan_usage_enabled">
      This account did not grant ChatGPT plan usage.
    </p>
    <dialog
      v-if="noticeAccount"
      ref="noticeDialog"
      aria-labelledby="plan-notice-title"
      @cancel.prevent
    >
      <h3 id="plan-notice-title">You’re using your ChatGPT plan</h3>
      <p>
        Eligible AI requests in Spoiless will use your ChatGPT plan. You can manage usage in
        <a href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer"
          >ChatGPT settings</a
        >.
      </p>
      <button type="button" @click="dismissPlanNotice">Got it</button>
    </dialog>
    <p v-if="revocationUnconfirmed" role="alert">
      Signed out locally, but we could not confirm remote revocation. Disconnect Spoiless in
      <a
        href="https://chatgpt.com/#settings/ConnectedApps"
        target="_blank"
        rel="noopener noreferrer"
        >ChatGPT settings</a
      >.
    </p>
    <p v-if="state?.status === 'denied'" role="status">Sign-in was declined. You can try again.</p>
    <p v-if="state?.status === 'expired'" role="status">Sign-in expired. Please try again.</p>
    <p v-if="state?.status === 'failed'" role="alert">Sign-in failed. Please try again.</p>
    <p v-if="state?.status === 'cancelled'" role="status">Sign-in was cancelled.</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <button
      v-if="state?.status === 'pending'"
      type="button"
      :disabled="busy"
      @click="act('/api/chatgpt/sign-in/cancel')"
    >
      Cancel sign-in
    </button>
    <button
      v-else-if="
        state?.status !== 'processing' &&
        (state?.status !== 'connected' ||
          selectedAccount !== accounts.find((account) => account.active)?.id)
      "
      type="button"
      data-oai-siwc-button
      :disabled="busy || !state"
      @click="act('/api/chatgpt/sign-in')"
    >
      Continue with ChatGPT
    </button>
    <button
      v-if="state?.status === 'saved' || state?.status === 'connected'"
      type="button"
      :disabled="busy"
      @click="signOut"
    >
      Sign out
    </button>
    <button v-if="error" type="button" @click="load">Retry</button>
  </section>
</template>

<style scoped>
.connection {
  margin-top: 24px;
  padding: 20px 24px;
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
label {
  display: block;
  font-size: 14px;
  margin-top: 12px;
}
select {
  font: inherit;
  max-width: 100%;
  min-height: 44px;
  padding: 8px;
}
button {
  font: inherit;
  min-height: 44px;
  padding: 8px 16px;
  border: 1px solid #222;
  border-radius: 6px;
  background: #222;
  color: white;
}
</style>
