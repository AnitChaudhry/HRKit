import { useEffect, useRef } from 'react';
import Hls from 'hls.js';
import { ArrowUpRight } from 'lucide-react';

function StartSection() {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const url =
      'https://stream.mux.com/9JXDljEVWYwWu01PUkAemafDugK89o01BR6zqJ3aS9u00A.m3u8';
    const video = videoRef.current;
    if (!video) return;

    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url;
    } else if (Hls.isSupported()) {
      const hls = new Hls();
      hls.loadSource(url);
      hls.attachMedia(video);
      return () => hls.destroy();
    }
  }, []);

  return (
    <section
      className="relative w-full overflow-hidden"
      style={{ minHeight: '500px' }}
    >
      <video
        ref={videoRef}
        autoPlay
        loop
        muted
        playsInline
        className="absolute inset-0 w-full h-full object-cover"
      />

      {/* Dark veil over the whole video so light streaks don't wash out text */}
      <div className="absolute inset-0 bg-black/55 z-0 pointer-events-none" />

      <div
        className="absolute top-0 left-0 right-0 z-0 pointer-events-none"
        style={{
          height: '200px',
          background: 'linear-gradient(to bottom, black, transparent)',
        }}
      />
      <div
        className="absolute bottom-0 left-0 right-0 z-0 pointer-events-none"
        style={{
          height: '200px',
          background: 'linear-gradient(to top, black, transparent)',
        }}
      />

      <div className="relative z-10 px-8 py-32 flex flex-col items-center text-center gap-6">
        <span className="liquid-glass rounded-full px-3.5 py-1 text-xs font-medium text-white font-body">
          How It Works
        </span>
        <h2
          className="text-4xl md:text-5xl lg:text-6xl font-heading italic text-white tracking-tight leading-[0.9] max-w-3xl"
          style={{ textShadow: '0 2px 20px rgba(0,0,0,0.5)' }}
        >
          You install it. You own it.
        </h2>
        <p
          className="text-white/90 font-body font-light text-sm md:text-base max-w-xl"
          style={{ textShadow: '0 1px 12px rgba(0,0,0,0.6)' }}
        >
          Five steps. No Docker. No SaaS. Your laptop runs the whole HR stack —
          employees, leave, payroll, performance, and an AI assistant wired to
          all of it.
        </p>
        <a
          href="https://github.com/AnitChaudhry/hrkit#quickstart"
          target="_blank"
          rel="noreferrer"
          className="liquid-glass-strong rounded-full px-6 py-3 text-white text-sm font-body flex items-center gap-2 mt-2"
        >
          Read the Quickstart <ArrowUpRight className="w-4 h-4" />
        </a>
      </div>
    </section>
  );
}

export default StartSection;
