import { ref } from "vue";

export const requestErrors = ref<string[]>([]);

function notify(message: string) {
  if (!requestErrors.value.includes(message)) requestErrors.value.push(message);
}

export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(input, init);
  } catch (error) {
    if (!init?.signal?.aborted && !(error instanceof DOMException && error.name === "AbortError")) {
      notify("Could not reach the backend. Check your connection and try again.");
    }
    throw error;
  }
  if (!response.ok) {
    const body: unknown = await response
      .clone()
      .json()
      .catch(() => null);
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : null;
    notify(
      response.status < 500 && typeof detail === "string" && detail.trim()
        ? detail
        : "The backend could not complete the request. Please try again.",
    );
  }
  return response;
}
