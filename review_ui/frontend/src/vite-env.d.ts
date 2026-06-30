/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the Review Agent API. Default: http://127.0.0.1:8000 */
  readonly VITE_API_BASE_URL?: string;
  /** "false" to call the live API; anything else (default) uses mock data. */
  readonly VITE_USE_MOCKS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
