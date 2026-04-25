import { useEffect, useRef } from 'react';

/**
 * Fixed-position canvas star field that lives behind all page content.
 *
 * - Stars are generated once per resize, then stay in place.
 * - Each star has a base brightness + an idle twinkle (sin wave on a phase
 *   it picks at birth, so the field looks alive without being noisy).
 * - A small cohort of stars are tagged "bright twinklers" and pulse harder
 *   so the eye finds focal points.
 * - Cursor proximity boosts brightness — stars within ~140 px of the
 *   pointer flare up, then settle back. Pointer leaving the page is
 *   treated as "no boost".
 * - Animation pauses when the tab is hidden (saves battery).
 *
 * Pointer-events are disabled so the canvas never steals clicks from the
 * UI above it.
 */

interface Star {
  x: number;
  y: number;
  r: number;          // radius in px
  base: number;       // baseline alpha 0..1
  amp: number;        // twinkle amplitude
  speed: number;      // twinkle speed
  phase: number;      // twinkle phase offset
  hue: number;        // tiny color shift
  bright: boolean;    // bright twinkler flag
}

const STAR_DENSITY = 1 / 5500;   // ~1 star per 5500px² — roughly 350 stars at 1440x1080
const POINTER_RADIUS = 140;
const POINTER_RADIUS_SQ = POINTER_RADIUS * POINTER_RADIUS;

function makeStars(width: number, height: number): Star[] {
  const target = Math.max(80, Math.floor(width * height * STAR_DENSITY));
  const stars: Star[] = [];
  for (let i = 0; i < target; i++) {
    const isBright = Math.random() < 0.08; // 8% are noticeably bright
    stars.push({
      x: Math.random() * width,
      y: Math.random() * height,
      r: isBright
        ? 0.9 + Math.random() * 1.4
        : 0.4 + Math.random() * 0.9,
      base: isBright ? 0.55 + Math.random() * 0.35 : 0.15 + Math.random() * 0.35,
      amp: isBright ? 0.35 + Math.random() * 0.25 : 0.1 + Math.random() * 0.18,
      speed: 0.4 + Math.random() * 1.6,
      phase: Math.random() * Math.PI * 2,
      hue: Math.random() < 0.18 ? 220 + Math.random() * 60 : 0, // some indigo/violet
      bright: isBright,
    });
  }
  return stars;
}

export default function StarField() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const starsRef = useRef<Star[]>([]);
  const pointerRef = useRef<{ x: number; y: number; active: boolean }>({
    x: -9999,
    y: -9999,
    active: false,
  });
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 2));

    const resize = () => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      starsRef.current = makeStars(w, h);
    };

    const onPointerMove = (ev: PointerEvent) => {
      pointerRef.current.x = ev.clientX;
      pointerRef.current.y = ev.clientY;
      pointerRef.current.active = true;
    };

    const onPointerLeave = () => {
      pointerRef.current.active = false;
      pointerRef.current.x = -9999;
      pointerRef.current.y = -9999;
    };

    const draw = (now: number) => {
      if (!startRef.current) startRef.current = now;
      const t = (now - startRef.current) / 1000;

      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      ctx.clearRect(0, 0, w, h);

      const px = pointerRef.current.x;
      const py = pointerRef.current.y;
      const pointerActive = pointerRef.current.active;

      for (const s of starsRef.current) {
        // Idle twinkle.
        let alpha = s.base + s.amp * Math.sin(s.phase + t * s.speed);

        // Pointer proximity boost.
        if (pointerActive) {
          const dx = s.x - px;
          const dy = s.y - py;
          const distSq = dx * dx + dy * dy;
          if (distSq < POINTER_RADIUS_SQ) {
            const k = 1 - distSq / POINTER_RADIUS_SQ; // 1 at center, 0 at edge
            alpha = Math.min(1, alpha + k * 0.7);
          }
        }
        if (alpha < 0) alpha = 0;
        if (alpha > 1) alpha = 1;

        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        if (s.hue) {
          ctx.fillStyle = `hsla(${s.hue}, 70%, 80%, ${alpha})`;
        } else {
          ctx.fillStyle = `rgba(255, 255, 255, ${alpha})`;
        }
        ctx.fill();

        // Bright twinklers get a soft halo when their alpha is high.
        if (s.bright && alpha > 0.6) {
          ctx.beginPath();
          ctx.arc(s.x, s.y, s.r * 3.2, 0, Math.PI * 2);
          ctx.fillStyle = s.hue
            ? `hsla(${s.hue}, 80%, 75%, ${(alpha - 0.6) * 0.18})`
            : `rgba(199, 210, 254, ${(alpha - 0.6) * 0.18})`;
          ctx.fill();
        }
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    const onVisibilityChange = () => {
      if (document.hidden) {
        if (rafRef.current != null) {
          cancelAnimationFrame(rafRef.current);
          rafRef.current = null;
        }
      } else if (rafRef.current == null) {
        rafRef.current = requestAnimationFrame(draw);
      }
    };

    resize();
    window.addEventListener('resize', resize);
    window.addEventListener('pointermove', onPointerMove, { passive: true });
    window.addEventListener('pointerleave', onPointerLeave);
    document.addEventListener('visibilitychange', onVisibilityChange);
    rafRef.current = requestAnimationFrame(draw);

    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      window.removeEventListener('resize', resize);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerleave', onPointerLeave);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      style={{
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100vh',
        zIndex: 0,
        pointerEvents: 'none',
        // Pure black backdrop. Earlier this had indigo + pink radial gradients
        // for atmosphere; they were leaking a faint blue tint near the top
        // edge of the viewport, which read as a stray blue line on a
        // black-only design. Stars supply all the visual interest.
        background: '#000000',
      }}
    />
  );
}
