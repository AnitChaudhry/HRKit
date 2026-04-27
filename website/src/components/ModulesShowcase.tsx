// Visual grid of all 11 HR modules with icons + one-line value props.
// Now also flags which are always-on core vs opt-in, so visitors see at
// a glance that the app is configurable, not a fixed feature list.

import {
  Users, Building2, BadgeCheck, FileText, CalendarDays,
  Clock, Wallet, LineChart, ListChecks, LogOut, UserPlus,
  ArrowUpRight,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

type Category = 'core' | 'hr' | 'hiring';

interface Module {
  icon: LucideIcon;
  name: string;
  blurb: string;
  category: Category;
}

const MODULES: Module[] = [
  { icon: Building2,    name: 'Departments',  blurb: 'Org tree with heads and parent-child structure.',                   category: 'core' },
  { icon: Users,        name: 'Employees',    blurb: 'Profiles, codes, salary, reports-to chain, full org chart.',         category: 'core' },
  { icon: BadgeCheck,   name: 'Roles',        blurb: 'Job titles + HR ladder (Team Lead → Manager → Director → VP).',      category: 'core' },
  { icon: FileText,     name: 'Documents',    blurb: 'Contracts, IDs, certificates — uploaded straight from the browser.', category: 'hr' },
  { icon: CalendarDays, name: 'Leave',        blurb: 'Types, balances, requests, approvals, calendar block on approve.',   category: 'hr' },
  { icon: Clock,        name: 'Attendance',   blurb: 'Daily check-in / check-out with automatic hour totals.',             category: 'hr' },
  { icon: Wallet,       name: 'Payroll',      blurb: 'Monthly runs, generate payslips for all active employees.',          category: 'hr' },
  { icon: LineChart,    name: 'Performance',  blurb: 'Review cycles, rubrics, scores, three-stage status flow.',           category: 'hr' },
  { icon: ListChecks,   name: 'Onboarding',   blurb: 'Per-employee task lists with owners and due dates.',                 category: 'hr' },
  { icon: LogOut,       name: 'Exits',        blurb: 'Exit interviews, KT status, asset returns, status flips automatically.', category: 'hr' },
  { icon: UserPlus,     name: 'Recruitment',  blurb: 'Drag-and-drop kanban, AI scoring, one-click promote-to-employee.',   category: 'hiring' },
];

const CATEGORY_LABEL: Record<Category, string> = {
  core: 'core',
  hr: 'HR',
  hiring: 'hiring',
};

const CATEGORY_STYLE: Record<Category, string> = {
  core:   'bg-indigo-500/15 text-indigo-300 border border-indigo-400/20',
  hr:     'bg-white/5 text-white/55 border border-white/10',
  hiring: 'bg-amber-500/15 text-amber-300 border border-amber-400/20',
};

export function ModulesShowcase() {
  return (
    <section id="modules" className="px-8 lg:px-16 py-24 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col items-center text-center mb-16">
        <span className="liquid-glass rounded-full px-3.5 py-1 text-xs font-medium text-white font-body">
          Pick what your team actually uses
        </span>
        <h2 className="text-4xl md:text-5xl lg:text-6xl font-heading italic text-white tracking-tight leading-[0.9] mt-4 max-w-3xl">
          Eleven modules. Three are core. The rest are yours to choose.
        </h2>
        <p className="text-white/60 font-body font-light text-sm md:text-base mt-5 max-w-2xl">
          The first-run wizard asks which features you want — pick a preset
          (HR-focused, Recruitment-focused, Core only) or check exactly the
          modules you need. Disabled modules vanish from the navigation,
          the CLI, and the AI assistant. Re-enable any time on
          <code className="mx-1 text-white/80">/settings</code>.
        </p>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {MODULES.map(({ icon: Icon, name, blurb, category }) => (
          <div
            key={name}
            className="liquid-glass rounded-2xl p-5 flex items-start gap-4 hover:bg-white/[0.03] transition-colors"
          >
            <div className="liquid-glass-strong rounded-full w-9 h-9 flex items-center justify-center shrink-0">
              <Icon className="w-4 h-4 text-white" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-white font-body font-medium text-sm">
                  {name}
                </span>
                <span className={`text-[9.5px] uppercase tracking-wider px-1.5 py-0.5 rounded ${CATEGORY_STYLE[category]}`}>
                  {CATEGORY_LABEL[category]}
                </span>
              </div>
              <p className="text-white/55 font-body font-light text-[12.5px] mt-1 leading-relaxed">
                {blurb}
              </p>
            </div>
          </div>
        ))}
      </div>

      {/* Footer link */}
      <div className="flex justify-center mt-12">
        <a
          href="https://github.com/AnitChaudhry/HRKit/blob/main/USER-MANUAL.md"
          target="_blank"
          rel="noreferrer"
          className="liquid-glass-strong rounded-full px-5 py-2.5 text-white text-sm font-body flex items-center gap-2"
        >
          Read the module reference <ArrowUpRight className="w-3.5 h-3.5" />
        </a>
      </div>
    </section>
  );
}

export default ModulesShowcase;
