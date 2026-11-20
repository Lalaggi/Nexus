import { useCallback, useEffect, useRef } from 'react';

interface UseDragOptions {
  /** Element to attach touch listeners to. Defaults to the document element. */
  element?: HTMLElement | null;
  /** Minimum travel in px before a drag is committed. */
  threshold?: number;
  /** How much horizontal movement must dominate vertical before claiming the gesture. */
  dominance?: number;
  /** Called once the gesture is committed to a horizontal drag. */
  onDragStart?: () => void;
  /** Called continuously during the drag with the delta from touch start. */
  onDrag?: (deltaX: number, deltaY: number) => void;
  /** Called on lift with the final delta and pixels-per-ms horizontal velocity. */
  onDragEnd?: (deltaX: number, deltaY: number, velocityX: number) => void;
}

/**
 * Finger-following drag gesture.
 *
 * Unlike the previous swipe detector (which only fired on lift), this reports the
 * live delta while the finger moves so UI can track the finger. It only claims the
 * gesture once movement is clearly horizontal and past a threshold, so ordinary
 * vertical scrolling is never interrupted.
 *
 * Listeners are non-passive on touchmove so we can preventDefault once a horizontal
 * drag is locked in (stopping the page from scrolling while the sidebar follows the
 * finger).
 */
export function useDrag({
  element,
  threshold = 15,
  dominance = 1.2,
  onDragStart,
  onDrag,
  onDragEnd,
}: UseDragOptions = {}) {
  const start = useRef<{ x: number; y: number; time: number } | null>(null);
  const last = useRef<{ x: number; y: number; time: number } | null>(null);
  const dragging = useRef(false);

  const onTouchStart = useCallback((event: TouchEvent) => {
    const target = event.target as HTMLElement | null;
    // Never intercept touches on focusable form elements.
    if (
      target &&
      (target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.tagName === 'SELECT')
    ) {
      return;
    }
    // Let horizontally-scrollable containers (e.g. tables) handle their own
    // touch gestures so swiping on them doesn't drag the sidebar.
    if (target && target.closest('table')) {
      return;
    }
    const touch = event.touches[0];
    const now = Date.now();
    start.current = { x: touch.clientX, y: touch.clientY, time: now };
    last.current = { ...start.current };
    dragging.current = false;
  }, []);

  const onTouchMove = useCallback(
    (event: TouchEvent) => {
      if (!start.current) return;
      const touch = event.touches[0];
      const now = Date.now();
      const dx = touch.clientX - start.current.x;
      const dy = touch.clientY - start.current.y;

      if (!dragging.current) {
        const horizontal = Math.abs(dx) > threshold;
        const dominates = Math.abs(dx) > Math.abs(dy) * dominance;
        if (horizontal && dominates) {
          dragging.current = true;
          onDragStart?.();
          event.preventDefault();
        } else if (Math.abs(dy) > threshold) {
          // Clearly a vertical scroll — abandon the gesture.
          start.current = null;
          dragging.current = false;
        }
        return;
      }

      // Locked into a horizontal drag: follow the finger and suppress scroll.
      event.preventDefault();
      onDrag?.(dx, dy);
      last.current = { x: touch.clientX, y: touch.clientY, time: now };
    },
    [threshold, dominance, onDragStart, onDrag]
  );

  const onTouchEnd = useCallback(
    (event: TouchEvent) => {
      if (!start.current) return;
      if (dragging.current && onDragEnd) {
        const touch = event.changedTouches[0];
        const now = Date.now();
        const dx = touch.clientX - start.current.x;
        const dy = touch.clientY - start.current.y;
        const dt = now - start.current.time;
        const velocityX = dt > 0 ? dx / dt : 0;
        onDragEnd(dx, dy, velocityX);
      }
      start.current = null;
      last.current = null;
      dragging.current = false;
    },
    [onDragEnd]
  );

  useEffect(() => {
    const el = element ?? document.documentElement;
    el.addEventListener('touchstart', onTouchStart, { passive: false });
    el.addEventListener('touchmove', onTouchMove, { passive: false });
    el.addEventListener('touchend', onTouchEnd, { passive: false });
    return () => {
      el.removeEventListener('touchstart', onTouchStart);
      el.removeEventListener('touchmove', onTouchMove);
      el.removeEventListener('touchend', onTouchEnd);
    };
  }, [element, onTouchStart, onTouchMove, onTouchEnd]);
}
