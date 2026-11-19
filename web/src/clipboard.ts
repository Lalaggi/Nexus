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
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      /* insecure origin, missing permission, or unfocused document */
    }
  }

  return legacyCopy(text);
}

function legacyCopy(text: string): boolean {
  if (typeof document === 'undefined') return false;

  const active = document.activeElement as HTMLElement | null;
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.setAttribute('aria-hidden', 'true');
  textarea.style.position = 'fixed';
  textarea.style.top = '0';
  textarea.style.left = '-9999px';
  textarea.style.width = '1px';
  textarea.style.height = '1px';
  textarea.style.opacity = '0';
  textarea.style.pointerEvents = 'none';

  document.body.appendChild(textarea);
  try {
    textarea.focus({ preventScroll: true });
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    textarea.remove();
    // Restore focus/selection so the click does not jump the page.
    if (active && typeof active.focus === 'function') {
      active.focus({ preventScroll: true });
    }
  }
}
