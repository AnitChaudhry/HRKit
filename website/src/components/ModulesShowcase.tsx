// Visual grid of all 11 HR modules with icons + one-line value props.
// This is what a buying HR manager wants to scan: "does it cover what I do?"

import {
  Users, Building2, BadgeCheck, FileText, CalendarDays,
  Clock, Wallet, LineChart, ListChecks, LogOut, UserPlus,
  ArrowUpRight,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

interface Module {
  icon: LucideIcon;
  name: string;
  blurb: string;
}

const MODULES: Module[] = [
  { icon: Users,        name: 'Employees',    blurb: 'Profiles, codes, salary, manager links — all in one table.' },
  { icon: Building2,    name: 'Departments',  blurb: 'Org tree with heads and parent-child structure.' },
  { icon: BadgeCheck,   name: 'Roles',        blurb: 'Job titles, levels, and the people in each one.' },
  { icon: FileText,     name: 'Documents',    blurb: 'Contracts, IDs, certificates — uploaded straight from the browser.' },
  { icon: CalendarDays, name: 'Leave',        blurb: 'Types, balances, requests, approvals, calendar block on approve.' },
  { icon: Clock,        name: 'Attendance',   blurb: 'Daily check-in / check-out with automatic hour totals.' },
  { icon: Wallet,       name: 'Payroll',      blurb: 'Monthly runs, generate payslips for all active employees.' },
  { icon: LineChart,    name: 'Performance',  blurb: 'Review cycles, rubrics, scores, three-stage status flow.' },
  { icon: ListChecks,   name: 'Onboarding',   blurb: 'Per-employee task lists with owners and due dates.' },
  { icon: LogOut,       name: 'Exits',        blurb: 'Exit interviews, KT status, asset returns, status flips automatically.' },
  { icon: UserPlus,     name: 'Recruitment',  blurb: 'Drag-and-drop kanban, AI scoring, one-click promote-to-employee.' },
];

export function ModulesShowcase() {
  return (
    <section id="modules" className="px-8 lg:px-16 py-24 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col items-center text-center mb-16">
        <span className="liquid-glass rounded-full px-3.5 py-1 text-xs font-medium text-white font-body">
          Eleven modules
        </span>
        <h2 className="text-4xl md:text-5xl lg:text-6xl font-heading italic text-white tracking-tight leading-[0.9] mt-4 max-w-3xl">
          Everything an HR person actually does.
        </h2>
        <p className="text-white/60 font-body font-light text-sm md:text-base mt-5 max-w-2xl">
          From the day someone applies through the day they exit — every
          touchpoint a small or growing HR team handles, in one local app.
        </p>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {MODULES.map(({ icon: Icon, name, blurb }) => (
          <div
            key={name}
            className="liquid-glass rounded-2xl p-5 flex items-start gap-4 hover:bg-white/[0.03] transition-colors"
          >
            <div className="liquid-glass-strong rounded-full w-9 h-9 flex items-center justify-center shrink-0">
              <Icon className="w-4 h-4 text-white" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-white font-body font-medium text-sm">
                {name}
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
          href="https://github.com/AnitChaudhry/hrkit/blob/main/USER-MANUAL.md"
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
