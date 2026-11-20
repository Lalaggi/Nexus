/**
 * Copy text to the clipboard.
 *
 * `navigator.clipboard` only exists in a secure context (https:// or
 * localhost). The web build is often opened over plain http on a LAN address,
 * and Android WebView can reject clipboard writes even on https://localhost,
 * so fall back to the legacy `execCommand('copy')` path instead of failing
 * silently. Returns whether the text made it to the clipboard.
 */
export async function copyText(text: string): Promise<boolean> {
  // Only touch the modern API in a secure context. On plain http it is usually
  // undefined, but some browsers expose it and reject the write; awaiting that
  // rejection consumes the click's transient user activation, which then makes
  // the execCommand fallback fail too.
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      console.log('[clipboard] copied via navigator.clipboard.writeText');
      return true;
    } catch (error) {
      console.warn('[clipboard] navigator.clipboard.writeText failed, falling back:', error);
    }
  }

  return legacyCopy(text);
}

/**
 * Copy on insecure origins (plain http LAN) and Android WebView.
 *
 * The old hidden-textarea + `select()` trick depends on the element being
 * focusable and the selection surviving until the copy runs, which is
 * unreliable on WebViews and in some desktop browsers over plain http.
 *
 * Instead let `execCommand('copy')` fire a `copy` event and write the data
 * straight into `clipboardData`. That needs no selection and no visible
 * element, and is the same fallback Open WebUI uses for plain-http LAN
 * deployments.
 */
function legacyCopy(text: string): boolean {
  if (typeof document === 'undefined') return false;

  const onCopy = (event: ClipboardEvent) => {
    event.preventDefault();
    event.clipboardData?.clearData();
    event.clipboardData?.setData('text/plain', text);
  };

  document.addEventListener('copy', onCopy);
  let ok = false;
  try {
    ok = document.execCommand('copy');
    console.log('[clipboard] execCommand(copy) result:', ok);
  } catch (error) {
    console.warn('[clipboard] execCommand(copy) threw:', error);
    ok = false;
  } finally {
    document.removeEventListener('copy', onCopy);
  }
  return ok;
}
