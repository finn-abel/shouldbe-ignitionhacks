// Every backend call lives in this module (doc 2 §3.4) — components never fetch directly.
// Endpoint functions are added alongside the steps that build their routes.

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
