type Testimonial = {
  quote: string;
  name: string;
  role: string;
};

const TESTIMONIALS: Testimonial[] = [
  {
    quote:
      "Replaced our $40/seat HRIS with one Python package on the founder's laptop. Took an afternoon.",
    name: 'Anita Rao',
    role: 'Founder, Stratha',
  },
  {
    quote:
      'The Composio integration was a three-line change. Now leave approvals fire calendar blocks automatically.',
    name: 'Marcus Webb',
    role: 'Ops Lead, Arcline',
  },
  {
    quote:
      "I rebranded it as 'Acme HR' in five minutes by setting one env var. Demoed it the same day.",
    name: 'Elena Voss',
    role: 'Indie founder',
  },
];

function Testimonials() {
  return (
    <section className="px-8 lg:px-16 py-24 max-w-7xl mx-auto">
      <div className="mb-16 text-center flex flex-col items-center gap-6">
        <span className="liquid-glass rounded-full px-3.5 py-1 text-xs font-medium text-white font-body">
          What They Say
        </span>
        <h2 className="text-4xl md:text-5xl lg:text-6xl font-heading italic text-white tracking-tight leading-[0.9]">
          Don't take our word for it.
        </h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {TESTIMONIALS.map((t) => (
          <div key={t.name} className="liquid-glass rounded-2xl p-8">
            <p className="text-white/80 font-body font-light text-sm italic leading-relaxed">
              "{t.quote}"
            </p>
            <div className="mt-6 pt-4 border-t border-white/10">
              <div className="text-white font-body font-medium text-sm">
                {t.name}
              </div>
              <div className="text-white/50 font-body font-light text-xs mt-1">
                {t.role}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default Testimonials;
