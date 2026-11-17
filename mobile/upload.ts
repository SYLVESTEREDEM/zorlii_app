export function uploadMultipart(url: string, method: string, body: FormData, token: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open(method, url);
    if (token) request.setRequestHeader("Authorization", `Bearer ${token}`);
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve();
        return;
      }
      let detail: unknown;
      try {
        detail = JSON.parse(request.responseText).detail;
      } catch {
        reject(new Error("Could not upload this media. Please try again."));
        return;
      }
      reject(new Error(typeof detail === "string" && detail ? detail : "Could not upload this media. Please try again."));
    };
    request.onerror = () => reject(new Error("Could not upload this media. Check your connection and try again."));
    request.onabort = () => reject(new Error("The media upload was cancelled."));
    request.ontimeout = () => reject(new Error("The media upload timed out. Please try again."));
    request.send(body);
  });
}
