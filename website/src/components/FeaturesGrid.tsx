import { Laptop, Boxes, MessageSquare, BadgeCheck } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

type Card = {
  Icon: LucideIcon;
  title: string;
  body: string;
};

const cards: Card[] = [
  {
    Icon: Laptop,
    title: 'Local, Not SaaS',
    body: "Runs on the HR person's laptop. No accounts to provision. No vendor lock-in. No monthly bill.",
  },
  {
    Icon: Boxes,
    title: '11 Modules, One Repo',
    body: 'Employees, departments, roles, documents, leave, attendance, payroll, performance, onboarding, exits, recruitment.',
  },
  {
    Icon: MessageSquare,
    title: 'Talk to Your Data',
    body: 'One chat box, all 11 modules. "Add Sarah as employee in Engineering." "List leave requests pending approval." Done.',
  },
  {
    Icon: BadgeCheck,
    title: 'MIT-Licensed',
    body: 'Fork it. Rebrand it. Ship your own version. Zero gatekeeping. Full audit trail in git.',
  },
];

function FeaturesGrid() {
  return (
    <section className="px-8 lg:px-16 py-24 max-w-7xl mx-auto">
      <div className="mb-16 flex flex-col items-start gap-4">
        <span className="liquid-glass rounded-full px-3.5 py-1 text-xs font-medium text-white font-body">
          Why HR-Kit
        </span>
        <h2 className="text-4xl md:text-5xl lg:text-6xl font-heading italic text-white tracking-tight leading-[0.9]">
          The difference is everything.
        </h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {cards.map(({ Icon, title, body }) => (
          <div key={title} className="liquid-glass rounded-2xl p-6">
            <div className="liquid-glass-strong rounded-full w-10 h-10 flex items-center justify-center mb-4">
              <Icon className="w-5 h-5 text-white" />
            </div>
            <h4 className="text-lg font-body font-medium text-white mb-2">
              {title}
            </h4>
            <p className="text-white/60 font-body font-light text-sm leading-relaxed">
              {body}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

export default FeaturesGrid;
