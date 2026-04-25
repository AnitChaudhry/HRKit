// Two alternating rows pairing HR-Kit-specific copy with custom HTML/CSS
// mockups. No external GIFs — every preview shows what the actual app does.

import { ArrowUpRight, Search } from 'lucide-react';

export function FeaturesChess() {
  return (
    <section className="px-8 lg:px-16 py-24 max-w-7xl mx-auto">
      {/* Section header */}
      <div className="flex flex-col items-center text-center mb-20">
        <span className="liquid-glass rounded-full px-3.5 py-1 text-xs font-medium text-white font-body">
          Built for HR teams
        </span>
        <h2 className="text-4xl md:text-5xl lg:text-6xl font-heading italic text-white tracking-tight leading-[0.9] mt-4 max-w-3xl">
          Every HR tool, on one laptop.
        </h2>
      </div>

      {/* Row 1: text-left, mockup right (employee directory) */}
      <div className="flex flex-col md:flex-row items-center gap-12 mb-32">
        <div className="flex-1">
          <h3 className="text-3xl md:text-4xl font-heading italic text-white leading-tight">
            One app for the entire employee lifecycle.
          </h3>
          <p className="text-white/60 font-body font-light text-sm md:text-base mt-4 max-w-md">
            Stop switching between an HRIS, a payroll tool, a leave tracker and
            a hiring kanban. HR-Kit ships eleven modules in one package — every
            employee record, every leave request, every payslip lives in a
            single SQLite file on your machine.
          </p>
          <a
            href="https://github.com/AnitChaudhry/hrkit/blob/main/USER-MANUAL.md#modules"
            target="_blank"
            rel="noreferrer"
            className="liquid-glass-strong rounded-full px-5 py-2.5 text-white text-sm font-body flex items-center gap-2 mt-6 w-fit"
          >
            Read the module reference <ArrowUpRight className="w-3.5 h-3.5" />
          </a>
        </div>
        <div className="flex-1 w-full">
          <EmployeeDirectoryMockup />
        </div>
      </div>

      {/* Row 2: text-right, mockup left (AI chat) */}
      <div className="flex flex-col md:flex-row-reverse items-center gap-12">
        <div className="flex-1">
          <h3 className="text-3xl md:text-4xl font-heading italic text-white leading-tight">
            Talk to your HR data. Skip the busywork.
          </h3>
          <p className="text-white/60 font-body font-light text-sm md:text-base mt-4 max-w-md">
            Paste an OpenRouter or Upfyn API key and a chat box appears that
            knows every module. "Add Sarah as Senior Engineer." "Approve all
            pending leave under three days." "Generate this month's payroll."
            Done in seconds, with a full audit trail.
          </p>
          <a
            href="https://github.com/AnitChaudhry/hrkit/blob/main/USER-MANUAL.md#ai-assistant"
            target="_blank"
            rel="noreferrer"
            className="liquid-glass-strong rounded-full px-5 py-2.5 text-white text-sm font-body flex items-center gap-2 mt-6 w-fit"
          >
            How the AI assistant works <ArrowUpRight className="w-3.5 h-3.5" />
          </a>
        </div>
        <div className="flex-1 w-full">
          <AIChatMockup />
        </div>
      </div>
    </section>
  );
}

// ---------- Inline mockup: employee directory ----------

const ROWS = [
  { code: 'EMP-0014', name: 'Sarah Chen',   dept: 'Engineering', role: 'Senior Engineer', status: 'active' },
  { code: 'EMP-0021', name: 'Marcus Webb',  dept: 'Operations',  role: 'Ops Lead',        status: 'on_leave' },
  { code: 'EMP-0024', name: 'Elena Voss',   dept: 'Design',      role: 'Brand Director',  status: 'active' },
  { code: 'EMP-0027', name: 'Anita Rao',    dept: 'Engineering', role: 'PM',              status: 'active' },
  { code: 'EMP-0031', name: 'Jordan Park',  dept: 'People',      role: 'Recruiter',       status: 'active' },
];

const STATUS_COLOR: Record<string, string> = {
  active:   'bg-emerald-500/15 text-emerald-300 border-emerald-500/20',
  on_leave: 'bg-amber-500/15 text-amber-300 border-amber-500/20',
  exited:   'bg-rose-500/15 text-rose-300 border-rose-500/20',
};

function EmployeeDirectoryMockup() {
  return (
    <div className="liquid-glass rounded-2xl overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-rose-400/70" />
          <div className="w-2.5 h-2.5 rounded-full bg-amber-400/70" />
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-400/70" />
          <div className="ml-3 text-white/50 text-xs font-body">acme-hr · employees</div>
        </div>
        <div className="text-white/40 text-[10px] font-body uppercase tracking-wider">localhost:8765</div>
      </div>

      {/* Module nav */}
      <div className="flex flex-wrap gap-1 px-4 py-2 border-b border-white/10 text-[11px] font-body">
        {['Employees', 'Departments', 'Leave', 'Attendance', 'Payroll', 'Performance', 'Recruitment'].map((m, i) => (
          <span
            key={m}
            className={
              i === 0
                ? 'px-2.5 py-1 rounded-md bg-white/15 text-white'
                : 'px-2.5 py-1 rounded-md text-white/55 hover:text-white'
            }
          >
            {m}
          </span>
        ))}
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between px-5 py-4">
        <div className="text-white text-base font-body font-medium">Employees</div>
        <div className="flex items-center gap-2">
          <div className="liquid-glass rounded-full px-3 py-1 flex items-center gap-1.5 text-[11px] text-white/60">
            <Search className="w-3 h-3" />
            <span>Search</span>
          </div>
          <span className="bg-white text-black rounded-full px-3 py-1 text-[11px] font-medium">+ Add</span>
        </div>
      </div>

      {/* Table */}
      <div className="px-2 pb-4">
        <table className="w-full text-[11px] font-body">
          <thead>
            <tr className="text-white/40 uppercase tracking-wider text-[10px]">
              <th className="text-left px-3 py-2 font-medium">Code</th>
              <th className="text-left px-3 py-2 font-medium">Name</th>
              <th className="text-left px-3 py-2 font-medium">Dept</th>
              <th className="text-left px-3 py-2 font-medium hidden sm:table-cell">Role</th>
              <th className="text-left px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((r) => (
              <tr key={r.code} className="border-t border-white/5 hover:bg-white/5">
                <td className="px-3 py-2.5 text-white/50">{r.code}</td>
                <td className="px-3 py-2.5 text-white">{r.name}</td>
                <td className="px-3 py-2.5 text-white/70">{r.dept}</td>
                <td className="px-3 py-2.5 text-white/70 hidden sm:table-cell">{r.role}</td>
                <td className="px-3 py-2.5">
                  <span className={`px-2 py-0.5 rounded-full border text-[10px] ${STATUS_COLOR[r.status]}`}>
                    {r.status.replace('_', ' ')}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------- Inline mockup: AI chat ----------

interface Message {
  role: 'user' | 'assistant';
  text: string;
}

const CHAT: Message[] = [
  { role: 'user',      text: 'Add Sarah Chen as Senior Engineer in Engineering, sarah@acme.com.' },
  { role: 'assistant', text: 'Created EMP-0042 — Sarah Chen, Senior Engineer in Engineering. Onboarding checklist applied (8 tasks). Want me to email her the welcome pack via Gmail?' },
  { role: 'user',      text: 'Yes. Also list leave requests pending approval.' },
  { role: 'assistant', text: 'Welcome email queued via Composio.\n\n3 leave requests pending:\n• Marcus Webb — Mar 12-15 (3 days)\n• Elena Voss — Mar 18-19 (2 days)\n• Anita Rao — Apr 1-5 (5 days)\n\nApprove the two short ones?' },
];

function AIChatMockup() {
  return (
    <div className="liquid-glass rounded-2xl overflow-hidden flex flex-col" style={{ minHeight: '420px' }}>
      {/* Top bar */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-rose-400/70" />
          <div className="w-2.5 h-2.5 rounded-full bg-amber-400/70" />
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-400/70" />
          <div className="ml-3 text-white/50 text-xs font-body">acme-hr · /chat</div>
        </div>
        <div className="text-white/40 text-[10px] font-body uppercase tracking-wider">openrouter · llama-3.3-70b</div>
      </div>

      {/* Messages */}
      <div className="flex-1 px-5 py-5 flex flex-col gap-3">
        {CHAT.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={
                m.role === 'user'
                  ? 'bg-white text-black rounded-2xl rounded-tr-sm px-3.5 py-2 text-[12px] font-body max-w-[78%] whitespace-pre-line'
                  : 'liquid-glass rounded-2xl rounded-tl-sm px-3.5 py-2 text-[12px] font-body text-white/90 max-w-[82%] whitespace-pre-line'
              }
            >
              {m.text}
            </div>
          </div>
        ))}
      </div>

      {/* Composer */}
      <div className="border-t border-white/10 px-4 py-3 flex items-center gap-2">
        <div className="flex-1 liquid-glass rounded-full px-4 py-2 text-[11px] text-white/45 font-body">
          Approve the two short ones
        </div>
        <span className="bg-white text-black rounded-full px-3.5 py-2 text-[11px] font-medium">Send</span>
      </div>
    </div>
  );
}

export default FeaturesChess;
