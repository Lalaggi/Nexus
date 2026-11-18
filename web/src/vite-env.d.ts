/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ASSISTANT_SERVER?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
