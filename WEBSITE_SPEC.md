# WEBSITE_SPEC.md — single source of truth for the Wave 5 website swarm

This file is read by every Wave 5 agent (W1-W4). The website lives at
`D:\Thinqmesh Wesbite\thinqmesh-hr\website\`. Follow the conventions and copy
exactly so the four agents' outputs compose into one cohesive landing page.

> **Project context.** HR-Kit is a fully open-source, local-first, white-label
> HR app. Python 3.10+, SQLite, one dependency. 11 HR modules, AI chat with
> BYOK keys (OpenRouter or Upfyn), Composio integrations (Gmail/Calendar/Drive),
> drag-and-drop hiring kanban, multipart file upload. This landing page is the
> public face of the project — it sells the *open-source story*, not a SaaS.

---

## 1. Stack & deps

```json
{
  "react": "^18.3.1",
  "react-dom": "^18.3.1",
  "react-router-dom": "^6.30.1",
  "motion": "^12.35.0",
  "hls.js": "^1.6.15",
  "lucide-react": "^0.462.0"
}
```

Build: Vite + TypeScript + Tailwind CSS. No shadcn/ui install needed — the
spec calls for shadcn but the components used (button-like elements, badges)
are simple enough to write inline as HTML with Tailwind classes.

## 2. File layout

```
website/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.js
├── index.html
├── public/
│   └── favicon.svg
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── index.css                       (CSS vars + glass utilities)
│   ├── assets/                         (placeholder for future images)
│   └── components/
│       ├── Navbar.tsx
│       ├── Hero.tsx
│       ├── BlurText.tsx
│       ├── StartSection.tsx
│       ├── FeaturesChess.tsx
│       ├── FeaturesGrid.tsx
│       ├── Stats.tsx
│       ├── Testimonials.tsx
│       └── CtaFooter.tsx
```

## 3. Glass utility classes (live in `src/index.css`)

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 213 45% 67%;
    --foreground: 0 0% 100%;
    --card: 213 45% 62%;
    --primary: 0 0% 100%;
    --primary-foreground: 213 45% 67%;
    --muted: 213 35% 60%;
    --muted-foreground: 0 0% 100% / 0.7;
    --border: 0 0% 100% / 0.2;
    --radius: 9999px;
  }
  body {
    @apply bg-black text-white font-body antialiased;
    margin: 0;
  }
}

@layer components {
  .liquid-glass {
    background: rgba(255, 255, 255, 0.01);
    background-blend-mode: luminosity;
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    border: none;
    box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.1);
    position: relative;
    overflow: hidden;
  }
  .liquid-glass::before {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    padding: 1.4px;
    background: linear-gradient(
      180deg,
      rgba(255, 255, 255, 0.45) 0%,
      rgba(255, 255, 255, 0.15) 20%,
      rgba(255, 255, 255, 0) 40%,
      rgba(255, 255, 255, 0) 60%,
      rgba(255, 255, 255, 0.15) 80%,
      rgba(255, 255, 255, 0.45) 100%
    );
    -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    -webkit-mask-composite: xor;
    mask-composite: exclude;
    pointer-events: none;
  }

  .liquid-glass-strong {
    background: rgba(255, 255, 255, 0.01);
    background-blend-mode: luminosity;
    backdrop-filter: blur(50px);
    -webkit-backdrop-filter: blur(50px);
    border: none;
    box-shadow:
      4px 4px 4px rgba(0, 0, 0, 0.05),
      inset 0 1px 1px rgba(255, 255, 255, 0.15);
    position: relative;
    overflow: hidden;
  }
  .liquid-glass-strong::before {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    padding: 1.4px;
    background: linear-gradient(
      180deg,
      rgba(255, 255, 255, 0.5) 0%,
      rgba(255, 255, 255, 0.2) 20%,
      rgba(255, 255, 255, 0) 40%,
      rgba(255, 255, 255, 0) 60%,
      rgba(255, 255, 255, 0.2) 80%,
      rgba(255, 255, 255, 0.5) 100%
    );
    -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    -webkit-mask-composite: xor;
    mask-composite: exclude;
    pointer-events: none;
  }
}
```

## 4. Tailwind config

`tailwind.config.ts` extends `fontFamily`:

```ts
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        heading: ["'Instrument Serif'", "serif"],
        body: ["'Barlow'", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;
```

`index.html` `<head>` includes the Google Fonts link:

```html
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Barlow:wght@300;400;500;600&display=swap" rel="stylesheet">
```

## 5. Asset URLs (used as-is — public CDN)

- Hero MP4 (CloudFront):
  `https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260307_083826_e938b29f-a43a-41ec-a153-3d4730578ab8.mp4`
- StartSection HLS (Mux):
  `https://stream.mux.com/9JXDljEVWYwWu01PUkAemafDugK89o01BR6zqJ3aS9u00A.m3u8`
- Stats HLS (Mux, render desaturated via `filter: saturate(0)`):
  `https://stream.mux.com/NcU3HlHeF7CUL86azTTzpy3Tlb00d6iF3BmCdFslMJYM.m3u8`
- CTA/Footer HLS (Mux):
  `https://stream.mux.com/8wrHPCX2dC3msyYU9ObwqNdm00u3ViXvOSHUMRYSEe5Q.m3u8`
- Hero poster placeholder: `/hero-bg.jpeg` (don't worry if absent — `<video>`
  falls back gracefully)
- Feature GIFs (chess rows):
  - Row 1: `https://motionsites.ai/assets/hero-finlytic-preview-CV9g0FHP.gif`
  - Row 2: `https://motionsites.ai/assets/hero-wealth-preview-B70idl_u.gif`

## 6. Adapted copy (HR-Kit themed — use these strings verbatim)

### Navbar links
`Home`, `Modules`, `Docs`, `GitHub`, `Pricing` (Pricing page = "Free, MIT-licensed")
+ right-side white pill: `Get Started` (links to GitHub repo)

### Hero
- **Badge text**: `Introducing the open-source local HR app.`
- **Heading** (BlurText): `The HR App That Lives On Your Laptop`
- **Subtext**: `All your HR data on your machine. Bring your own AI key. White-label your brand. Open source under MIT.`
- **CTA buttons**: `Get Started` (liquid-glass-strong, ArrowUpRight) + `View on GitHub` (text only with Play icon swapped for `Github` icon if available, else just text)
- **Trusted by bar**: `Built on the shoulders of` + 5 names rendered in heading italic: `Python`, `SQLite`, `PydanticAI`, `Composio`, `OpenRouter`

### StartSection ("How It Works")
- **Badge**: `How It Works`
- **Heading**: `You install it. You own it.`
- **Subtext**: `Five steps. No Docker. No SaaS. Your laptop runs the whole HR stack — employees, leave, payroll, performance, and an AI assistant wired to all of it.`
- **CTA**: `Read the Quickstart` (liquid-glass-strong)

### FeaturesChess

**Row 1 (text-left, gif-right):**
- Title: `Folder-native. DB-primary. AI-augmented.`
- Body: `Every employee record in SQLite. Every attachment on your filesystem. Every workflow extendable by a Python module or a Composio action. Drop in your own modules and they auto-register.`
- Button: `Browse the modules`

**Row 2 (text-right, gif-left, flex-row-reverse):**
- Title: `Bring your own keys. Own your stack.`
- Body: `OpenRouter for free models. Upfyn for paid. Composio for Gmail, Calendar, Drive. Swap any provider, anytime — your keys live in your machine, not a vendor's database.`
- Button: `See integrations`

### FeaturesGrid ("Why HR-Kit") — 4 cards
| Icon | Title | Body |
|---|---|---|
| `Laptop` | `Local, Not SaaS` | `Runs on the HR person's laptop. No accounts to provision. No vendor lock-in. No monthly bill.` |
| `Boxes` | `11 Modules, One Repo` | `Employees, departments, roles, documents, leave, attendance, payroll, performance, onboarding, exits, recruitment.` |
| `MessageSquare` | `Talk to Your Data` | `One chat box, all 11 modules. "Add Sarah as employee in Engineering." "List leave requests pending approval." Done.` |
| `BadgeCheck` | `MIT-Licensed` | `Fork it. Rebrand it. Ship your own version. Zero gatekeeping. Full audit trail in git.` |

(Use lucide-react icons. If any of those names aren't in lucide, fall back to
`Zap`, `Layers`, `MessageCircle`, `Shield` respectively.)

### Stats — 4 numbers
| Value | Label |
|---|---|
| `11` | `HR modules` |
| `72` | `Tests passing` |
| `1` | `Dependency` |
| `5` | `Steps to setup` |

### Testimonials — 3 cards (community-quote placeholders)
1. `"Replaced our $40/seat HRIS with one Python package on the founder's laptop. Took an afternoon."` — `Anita Rao`, `Founder, Stratha`
2. `"The Composio integration was a three-line change. Now leave approvals fire calendar blocks automatically."` — `Marcus Webb`, `Ops Lead, Arcline`
3. `"I rebranded it as 'Acme HR' in five minutes by setting one env var. Demoed it the same day."` — `Elena Voss`, `Indie founder`

### CTA + Footer
- **Heading**: `Your HR stack, on your terms.`
- **Subtext**: `Clone the repo. Paste your keys. Ship your version. No commitment, no contract — just the source code.`
- **Buttons**: `Star on GitHub` (liquid-glass-strong) + `Read the Docs` (bg-white text-black)
- **Footer bar**: `© 2026 HR-Kit contributors · MIT License` (left), links: `GitHub`, `Docs`, `Discussions` (right)

## 7. Section structure & shared design patterns

Same as the original spec — every section uses these patterns:

- **Section badge**: `liquid-glass rounded-full px-3.5 py-1 text-xs font-medium text-white font-body`
- **Section heading**: `text-4xl md:text-5xl lg:text-6xl font-heading italic text-white tracking-tight leading-[0.9]`
- **Section body text**: `text-white/60 font-body font-light text-sm md:text-base`
- **Primary CTA**: `liquid-glass-strong rounded-full px-5 py-2.5` with `ArrowUpRight` icon
- **Secondary CTA**: `bg-white text-black rounded-full px-5 py-2.5`
- **Card containers**: `liquid-glass rounded-2xl`
- **Video overlay fades**: top + bottom `linear-gradient(to bottom/top, black, transparent)` 200px tall (300px on hero bottom), `pointer-events-none`

## 8. Animation patterns

- `BlurText`: word-by-word stagger from bottom; each `motion.span` animates
  `{filter: 'blur(10px)', opacity: 0, y: 50}` → `{filter: 'blur(5px)', opacity: 0.5, y: -5}` →
  `{filter: 'blur(0px)', opacity: 1, y: 0}`. Stagger by index × 200ms.
  IntersectionObserver triggers it.
- Hero subtext: `motion.p` blur-in (10px → 0px), opacity 0→1, y 20→0, delay 0.8s, duration 0.6s.
- Hero CTA buttons: same blur-in, delay 1.1s.

## 9. App.tsx top-level structure

```tsx
<div className="bg-black min-h-screen">
  <div className="relative z-10">
    <Navbar />
    <Hero />
    <div className="bg-black">
      <StartSection />
      <FeaturesChess />
      <FeaturesGrid />
      <Stats />
      <Testimonials />
      <CtaFooter />
    </div>
  </div>
</div>
```

## 10. Per-agent ownership (no overlaps)

| Agent | Files |
|---|---|
| W1 Scaffold | `package.json`, `vite.config.ts`, `tsconfig.json`, `tailwind.config.ts`, `postcss.config.js`, `index.html`, `src/main.tsx`, `src/App.tsx`, `src/index.css`, `public/favicon.svg`, `.gitignore` (in website/) |
| W2 Top | `src/components/Navbar.tsx`, `src/components/Hero.tsx`, `src/components/BlurText.tsx` |
| W3 Mid | `src/components/StartSection.tsx`, `src/components/FeaturesChess.tsx`, `src/components/FeaturesGrid.tsx` |
| W4 Bottom | `src/components/Stats.tsx`, `src/components/Testimonials.tsx`, `src/components/CtaFooter.tsx` |

Agents must NOT touch files outside their list.

## 11. Definition of done (per agent)

- All listed files exist.
- TypeScript: no `any` unless necessary; type props.
- Imports use `import { Foo } from 'motion/react'` (the `motion` package re-exports under `motion/react`).
- HLS playback: import `Hls from 'hls.js'`, in `useEffect` call `new Hls()`,
  `hls.loadSource(url)`, `hls.attachMedia(videoRef.current!)`. Always check
  `videoRef.current.canPlayType('application/vnd.apple.mpegurl')` first
  (Safari) and use native `src=` if true.
- All copy strings come from Section 6 verbatim.
- Don't import any Tailwind plugin or shadcn package — pure Tailwind utilities
  + the two glass classes from `index.css`.
- Report files written, line counts, deviations.

`npm install` and `npm run build` must succeed at the end (Wave 5 verify
step — me, after all 4 agents land).
