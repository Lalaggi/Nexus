/**
 * Copy text to the clipboard.
 *
 * Tries the modern Clipboard API first (requires a secure context and user
 * activation), then falls back to the legacy document.execCommand('copy') for
 * insecure origins (plain HTTP LAN) and Android WebView where the modern API
 * is blocked or unavailable. Returns whether the text made it to the clipboard.
 */
export async function copyText(text: string): Promise<boolean> {
  // 1. Modern Clipboard API — only available in secure contexts (HTTPS,
  //    localhost) and requires transient user activation (satisfied by the
  //    click handler that calls this).
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      console.debug('[clipboard] copied via navigator.clipboard.writeText');
      return true;
    } catch (error) {
      console.debug(
        '[clipboard] navigator.clipboard.writeText failed, falling back:',
        error,
      );
    }
  }

  // 2. Legacy fallback — document.execCommand('copy') works on insecure
  //    origins and is the only option on some Android WebViews.
  return legacyCopy(text);
}

function legacyCopy(text: string): boolean {
  if (typeof document === 'undefined') return false;

  const active = document.activeElement as HTMLElement | null;
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.setAttribute('aria-hidden', 'true');

  // Visually hidden but still in the document so it can be focused and
  // selected. Off-screen positioning (left: -9999px) can make the element
  // unfocusable on some WebViews, so we keep it at the origin with zero size.
  textarea.style.position = 'fixed';
  textarea.style.left = '0';
  textarea.style.top = '0';
  textarea.style.width = '0';
  textarea.style.height = '0';
  textarea.style.opacity = '0';
  textarea.style.pointerEvents = 'none';
  textarea.style.overflow = 'hidden';

  document.body.appendChild(textarea);
  let ok = false;
  try {
    textarea.focus({ preventScroll: true });
    textarea.select();
    ok = document.execCommand('copy');
    console.debug('[clipboard] execCommand(copy) result:', ok);
  } catch (error) {
    console.debug('[clipboard] execCommand(copy) threw:', error);
    ok = false;
  } finally {
    textarea.remove();
    // Restore focus/selection so the click does not jump the page.
    if (active && typeof active.focus === 'function') {
      try {
        active.focus({ preventScroll: true });
      } catch {
        /* best effort */
      }
    }
  }
  return ok;
}
