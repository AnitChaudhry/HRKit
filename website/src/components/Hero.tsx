import { motion } from 'motion/react';
import { ArrowUpRight, Github } from 'lucide-react';
import { BlurText } from './BlurText';

export function Hero() {
  return (
    <section className="relative overflow-hidden" style={{ height: '1100px' }}>
      {/* Video background */}
      <video
        autoPlay
        loop
        muted
        playsInline
        poster="/hero-bg.jpeg"
        className="absolute left-0 w-full h-auto object-contain z-0"
        style={{ top: '20%' }}
      >
        <source
          src="https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260307_083826_e938b29f-a43a-41ec-a153-3d4730578ab8.mp4"
          type="video/mp4"
        />
      </video>

      {/* Dark overlay */}
      <div className="absolute inset-0 bg-black/5 z-0" />

      {/* Bottom gradient fade — bigger so the partners area below is solid black */}
      <div
        className="absolute bottom-0 left-0 right-0 z-0 pointer-events-none"
        style={{
          height: '450px',
          background: 'linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.7) 40%, black 80%)',
        }}
      />

      {/* Content */}
      <div
        className="relative z-10 flex flex-col items-center text-center px-8"
        style={{ paddingTop: '150px' }}
      >
        {/* Badge pill */}
        <div className="liquid-glass rounded-full px-1 py-1 inline-flex items-center gap-2">
          <span className="bg-white text-black rounded-full px-3 py-1 text-xs font-semibold">
            New
          </span>
          <span className="px-3 text-xs text-white/90 font-body">
            Introducing the open-source local HR app.
          </span>
        </div>

        {/* Heading */}
        <BlurText
          text="The HR App That Lives On Your Laptop"
          className="text-6xl md:text-7xl lg:text-[5.5rem] font-heading italic text-white leading-[0.8] max-w-2xl mt-6 tracking-[-4px]"
          delay={100}
        />

        {/* Subtext */}
        <motion.p
          initial={{ filter: 'blur(10px)', opacity: 0, y: 20 }}
          animate={{ filter: 'blur(0px)', opacity: 1, y: 0 }}
          transition={{ delay: 0.8, duration: 0.6 }}
          className="text-sm md:text-base text-white font-body font-light leading-tight mt-6 max-w-xl"
        >
          All your HR data on your machine. Bring your own AI key. White-label
          your brand. Open source under MIT.
        </motion.p>

        {/* CTA buttons */}
        <motion.div
          initial={{ filter: 'blur(10px)', opacity: 0, y: 20 }}
          animate={{ filter: 'blur(0px)', opacity: 1, y: 0 }}
          transition={{ delay: 1.1, duration: 0.6 }}
          className="flex items-center gap-4 mt-8"
        >
          <a
            href="https://github.com/AnitChaudhry/HRKit"
            target="_blank"
            rel="noreferrer"
            className="liquid-glass-strong rounded-full px-5 py-2.5 text-white font-body text-sm flex items-center gap-2"
          >
            <Github className="w-4 h-4" /> Star on GitHub <ArrowUpRight className="w-4 h-4" />
          </a>
          <a
            href="https://github.com/AnitChaudhry/HRKit#readme"
            target="_blank"
            rel="noreferrer"
            className="text-white/80 hover:text-white font-body text-sm flex items-center gap-2"
          >
            Read the Docs
          </a>
        </motion.div>
      </div>

      {/* Partners bar pinned to the bottom of the hero, in the dark gradient */}
      <div className="absolute bottom-0 left-0 right-0 z-10 pb-16 px-8">
        <div className="flex flex-col items-center text-center">
          <span className="liquid-glass rounded-full px-3.5 py-1 text-xs text-white/70 font-body">
            Built on the shoulders of
          </span>
          <div className="flex flex-wrap items-center justify-center gap-x-12 gap-y-4 md:gap-x-16 mt-6">
            {['Python', 'SQLite', 'PydanticAI', 'Composio', 'OpenRouter', 'Upfyn AI'].map((name) => (
              <span
                key={name}
                className="text-2xl md:text-3xl font-heading italic text-white/90"
              >
                {name}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export default Hero;
