import { useCallback, useEffect, useRef } from 'react';

export type SwipeDirection = 'left' | 'right' | 'up' | 'down';

interface UseSwipeOptions {
  /** Element to attach touch listeners to. Defaults to the document element. */
  element?: HTMLElement | null;
  /** Called when a deliberate swipe is detected. */
  onSwipe?: (direction: SwipeDirection, distance: number, startX: number) => void;
  /** Minimum travel in px before a swipe is reported. */
  threshold?: number;
  /** Only report swipes that start within this many px of the given edge. */
  edge?: 'left' | 'right' | null;
}

/**
 * Minimal touch swipe detector.
 *
 * Listeners are passive, so native scrolling and taps keep working — we only
 * observe touches and report on touchEnd. A swipe is reported when the touch
 * travels at least `threshold` px in one dominant direction.
 *
 * NOTE (Android back-gesture zones): the system back gesture also starts from
 * the screen edges. The edge band is kept narrow and requires a deliberate
 * swipe to reduce accidental conflicts; a later refinement can gate on velocity
 * or hook into Capacitor gesture exclusions.
 */
export function useSwipe({
  element,
  onSwipe,
  threshold = 44,
  edge,
}: UseSwipeOptions = {}) {
  const start = useRef<{ x: number; y: number } | null>(null);
  const direction = useRef<SwipeDirection | null>(null);

  const onTouchStart = useCallback((event: TouchEvent) => {
    const touch = event.touches[0];
    start.current = { x: touch.clientX, y: touch.clientY };
    direction.current = null;
  }, []);

  const onTouchMove = useCallback((event: TouchEvent) => {
    if (!start.current) return;
    const touch = event.touches[0];
    const dx = touch.clientX - start.current.x;
    const dy = touch.clientY - start.current.y;
    direction.current =
      Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : dy > 0 ? 'down' : 'up';
  }, []);

  const onTouchEnd = useCallback(
    (event: TouchEvent) => {
      if (!start.current || !direction.current || !onSwipe) return;
      const touch = event.changedTouches[0];
      const dx = touch.clientX - start.current.x;
      const dy = touch.clientY - start.current.y;
      const distance =
        direction.current === 'left' || direction.current === 'right' ? Math.abs(dx) : Math.abs(dy);
      if (distance < threshold) return;
      if (edge === 'left' && start.current.x > 32) return;
      if (edge === 'right' && start.current.x < window.innerWidth - 32) return;
      onSwipe(direction.current, distance, start.current.x);
    },
    [onSwipe, threshold, edge],
  );

  useEffect(() => {
    const el = element ?? document.documentElement;
    el.addEventListener('touchstart', onTouchStart, { passive: true });
    el.addEventListener('touchmove', onTouchMove, { passive: true });
    el.addEventListener('touchend', onTouchEnd, { passive: true });
    return () => {
      el.removeEventListener('touchstart', onTouchStart);
      el.removeEventListener('touchmove', onTouchMove);
      el.removeEventListener('touchend', onTouchEnd);
    };
  }, [element, onTouchStart, onTouchMove, onTouchEnd]);
}
