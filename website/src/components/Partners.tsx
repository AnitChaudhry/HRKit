// Trusted-by / built-on bar — sits in the dark section between Hero and the
// rest of the page so the white text never collides with hero video imagery.

const STACK = ['Python', 'SQLite', 'PydanticAI', 'Composio', 'OpenRouter'];

export function Partners() {
  return (
    <section className="relative bg-black px-8 py-20 lg:py-24">
      <div className="max-w-6xl mx-auto flex flex-col items-center text-center">
        <span className="liquid-glass rounded-full px-3.5 py-1 text-xs text-white/70 font-body">
          Built on the shoulders of
        </span>
        <div className="flex flex-wrap items-center justify-center gap-x-12 gap-y-6 md:gap-x-16 mt-8">
          {STACK.map((name) => (
            <span
              key={name}
              className="text-2xl md:text-3xl font-heading italic text-white/85 hover:text-white transition-colors"
            >
              {name}
            </span>
          ))}
        </div>
        <p className="text-white/40 font-body font-light text-xs md:text-sm mt-6 max-w-md">
          Standard, boring, well-loved tech. No exotic dependencies. No vendor
          you've never heard of.
        </p>
      </div>
    </section>
  );
}

export default Partners;
