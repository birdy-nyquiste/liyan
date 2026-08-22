import createClient from "openapi-fetch";

import type { paths } from "./schema";

export async function serverIsAlive(): Promise<boolean> {
  const api = createClient<paths>({
    baseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  });
  const { data, error } = await api.GET("/health/live");

  if (error || data?.status !== "alive") {
    return false;
  }

  return true;
}
