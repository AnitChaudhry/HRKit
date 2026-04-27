import { useEffect, useRef } from 'react';
import Hls from 'hls.js';
import { Github, ArrowUpRight } from 'lucide-react';

function CtaFooter() {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const url =
      'https://stream.mux.com/8wrHPCX2dC3msyYU9ObwqNdm00u3ViXvOSHUMRYSEe5Q.m3u8';
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
      style={{ minHeight: '600px' }}
    >
      <video
        ref={videoRef}
        autoPlay
        loop
        muted
        playsInline
        className="absolute inset-0 w-full h-full object-cover"
      />

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

      <div className="relative z-10 px-8 py-24 flex flex-col items-center text-center gap-6">
        <h2 className="text-5xl md:text-6xl lg:text-7xl font-heading italic text-white leading-[0.85] max-w-3xl">
          Your HR stack, on your terms.
        </h2>
        <p className="text-white/60 font-body font-light text-sm md:text-base max-w-xl">
          Install once. Run forever. Bring your own AI key. Open source under
          AGPL-3.0 — your data never leaves your laptop.
        </p>
        <div className="flex flex-wrap justify-center gap-3">
          <a
            href="https://github.com/AnitChaudhry/HRKit"
            target="_blank"
            rel="noreferrer"
            className="bg-white text-black rounded-full px-6 py-3 text-sm font-body font-medium flex items-center gap-2"
          >
            <Github className="w-4 h-4" /> Star on GitHub
          </a>
          <a
            href="https://github.com/AnitChaudhry/HRKit#readme"
            target="_blank"
            rel="noreferrer"
            className="liquid-glass-strong rounded-full px-6 py-3 text-white text-sm font-body flex items-center gap-2"
          >
            Read the Docs <ArrowUpRight className="w-4 h-4" />
          </a>
        </div>
      </div>

      <div className="mt-32 pt-8 border-t border-white/10 flex flex-col md:flex-row justify-between items-center gap-3 max-w-7xl mx-auto px-8 w-full relative z-10">
        <div className="text-white/40 text-xs font-body text-center md:text-left">
          © 2026 <strong className="text-white/60">Anit Chaudhary</strong> · AGPL-3.0
          {' · '}<a
            href="https://github.com/AnitChaudhry/HRKit/blob/main/COMMERCIAL.md"
            target="_blank"
            rel="noreferrer"
            className="text-white/60 hover:text-white"
          >Commercial license</a>
          {' · '}<a
            href="https://github.com/AnitChaudhry/HRKit/blob/main/TRADEMARK.md"
            target="_blank"
            rel="noreferrer"
            className="text-white/60 hover:text-white"
          >Trademark</a>
        </div>
        <div className="flex gap-6 text-white/40 text-xs font-body">
          <a href="https://github.com/AnitChaudhry/HRKit" target="_blank" rel="noreferrer">GitHub</a>
          <a href="https://github.com/AnitChaudhry/HRKit#readme" target="_blank" rel="noreferrer">Docs</a>
          <a href="https://github.com/AnitChaudhry/HRKit/discussions" target="_blank" rel="noreferrer">Discussions</a>
        </div>
      </div>
    </section>
  );
}

export default CtaFooter;
