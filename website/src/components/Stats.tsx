import { useEffect, useRef } from 'react';
import Hls from 'hls.js';

type Stat = {
  value: string;
  label: string;
};

const STATS: Stat[] = [
  { value: '$0',   label: 'Per seat, forever' },
  { value: '11',   label: 'HR modules included' },
  { value: '100%', label: 'On your machine' },
  { value: 'MIT',  label: 'License — fork it freely' },
];

function Stats() {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const url =
      'https://stream.mux.com/NcU3HlHeF7CUL86azTTzpy3Tlb00d6iF3BmCdFslMJYM.m3u8';
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
        style={{ filter: 'saturate(0)' }}
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

      <div className="relative z-10 px-8 py-24 flex justify-center">
        <div className="liquid-glass rounded-3xl p-12 md:p-16 max-w-5xl w-full">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
            {STATS.map((stat) => (
              <div key={stat.label}>
                <div className="text-4xl md:text-5xl lg:text-6xl font-heading italic text-white">
                  {stat.value}
                </div>
                <div className="text-white/60 font-body font-light text-sm mt-2">
                  {stat.label}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export default Stats;
