import { Star } from 'lucide-react';

// HR-Kit is a local Python app the user installs themselves — the website
// is marketing only. CTAs drive to GitHub + the docs in the repo.

const GITHUB_URL = 'https://github.com/AnitChaudhry/hrkit';
const DOCS_URL = 'https://github.com/AnitChaudhry/hrkit#readme';

export function Navbar() {
  return (
    <nav className="fixed top-4 left-0 right-0 z-50 px-8 lg:px-16 py-3 flex items-center justify-between">
      {/* Logo */}
      <a
        href="#home"
        className="h-12 w-12 rounded-full liquid-glass flex items-center justify-center font-heading italic text-white text-xl"
      >
        H
      </a>

      {/* Center pill (desktop) */}
      <div className="hidden md:flex liquid-glass rounded-full px-1.5 py-1 items-center gap-1">
        <a
          href="#home"
          className="px-3 py-2 text-sm font-medium text-white/90 font-body hover:text-white"
        >
          Home
        </a>
        <a
          href="#modules"
          className="px-3 py-2 text-sm font-medium text-white/90 font-body hover:text-white"
        >
          Modules
        </a>
        <a
          href={DOCS_URL}
          className="px-3 py-2 text-sm font-medium text-white/90 font-body hover:text-white"
        >
          Docs
        </a>
        <a
          href={GITHUB_URL}
          className="px-3 py-2 text-sm font-medium text-white/90 font-body hover:text-white"
        >
          GitHub
        </a>
        <a
          href={GITHUB_URL}
          target="_blank"
          rel="noreferrer"
          className="bg-white text-black rounded-full px-3.5 py-1.5 text-sm font-medium flex items-center gap-1"
        >
          <Star className="w-3.5 h-3.5" /> Star on GitHub
        </a>
      </div>

      {/* Right (desktop placeholder, mobile shows Star CTA) */}
      <div className="hidden md:flex" />
      <a
        href={GITHUB_URL}
        target="_blank"
        rel="noreferrer"
        className="md:hidden bg-white text-black rounded-full px-3 py-1.5 text-xs font-medium flex items-center gap-1"
      >
        <Star className="w-3 h-3" /> Star
      </a>
    </nav>
  );
}

export default Navbar;
