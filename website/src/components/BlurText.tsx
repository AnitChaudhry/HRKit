import { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';

interface BlurTextProps {
  text: string;
  className?: string;
  delay?: number;
  animateBy?: 'words' | 'letters';
  direction?: 'top' | 'bottom';
}

export function BlurText({
  text,
  className,
  delay = 200,
  animateBy = 'words',
  direction = 'bottom',
}: BlurTextProps) {
  const containerRef = useRef<HTMLSpanElement | null>(null);
  const [inView, setInView] = useState(false);

  const tokens = animateBy === 'words' ? text.split(' ') : text.split('');

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setInView(true);
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.1 }
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const yStart = direction === 'top' ? -50 : 50;
  const yMid = direction === 'top' ? 5 : -5;

  const initialKeyframe = { filter: 'blur(10px)', opacity: 0, y: yStart };
  const animateKeyframes = inView
    ? {
        filter: ['blur(10px)', 'blur(5px)', 'blur(0px)'],
        opacity: [0, 0.5, 1],
        y: [yStart, yMid, 0],
      }
    : initialKeyframe;

  return (
    <span ref={containerRef} className={className}>
      {tokens.map((token, index) => (
        <motion.span
          key={`${token}-${index}`}
          initial={initialKeyframe}
          animate={animateKeyframes}
          transition={{
            delay: (index * delay) / 1000,
            duration: 0.7,
            times: [0, 0.5, 1],
          }}
          style={{
            display: 'inline-block',
            marginRight: animateBy === 'words' ? '0.25em' : undefined,
            willChange: 'filter, opacity, transform',
          }}
        >
          {token}
        </motion.span>
      ))}
    </span>
  );
}

export default BlurText;
