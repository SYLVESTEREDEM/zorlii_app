const RETRY_DELAYS_MS = [500, 1500] as const;

export function isTransientPushServiceUnavailable(error: unknown) {
  if (!error || typeof error !== "object") return false;
  const candidate = error as { code?: unknown; message?: unknown };
  const code = typeof candidate.code === "string" ? candidate.code : "";
  const message = typeof candidate.message === "string" ? candidate.message : "";
  return /SERVICE_NOT_AVAILABLE/i.test(`${code} ${message}`);
}

export function pushRegistrationErrorMessage(error: unknown) {
  if (isTransientPushServiceUnavailable(error)) {
    return "Google Play services temporarily could not provide a notification token (SERVICE_NOT_AVAILABLE). Zorlii is still available. Check your connection or switch between Wi-Fi and mobile data, then try enabling activity alerts again.";
  }
  return error instanceof Error ? error.message : "Could not register this device for phone notifications.";
}

export async function retryTransientPushOperation<T>(
  operation: () => Promise<T>,
  wait: (milliseconds: number) => Promise<void> = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)),
) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      if (!isTransientPushServiceUnavailable(error) || attempt >= RETRY_DELAYS_MS.length) throw error;
      await wait(RETRY_DELAYS_MS[attempt]);
    }
  }
}
