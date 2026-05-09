import React from "react";

const params = new URLSearchParams(window.location.search);
const isPaid = params.get("paid") === "true";

const STRIPE_CHECKOUT_URL = "https://buy.stripe.com/6oU8wHeHTclU8Yi9Xf0oM02";

const CATEGORY_LABELS = {
  ai_presence: "AI Presence",
  seo_strength: "SEO Strength",
  authority: "Authority Signals",
  performance: "Website Performance",
};

const CATEGORY_ORDER = ["ai_presence", "seo_strength", "authority", "performance"];

function scoreColor(score) {
  if (score >= 75) return { text: "text-emerald-600", bar: "bg-emerald-500", ring: "ring-emerald-200" };
  if (score >= 50) return { text: "text-amber-600", bar: "bg-amber-500", ring: "ring-amber-200" };
  return { text: "text-rose-600", bar: "bg-rose-500", ring: "ring-rose-200" };
}

function HeroScore({ score, trade }) {
  const c = scoreColor(score);
  const peer = trade && trade.trim() ? trade.trim() : "competitors";
  return (
    <section className="flex flex-col items-center text-center pt-14 sm:pt-20 pb-10">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 mb-5">
        Your AI visibility score
      </p>
      <div className={`flex items-baseline justify-center rounded-full ring-[10px] ${c.ring} w-44 h-44 sm:w-52 sm:h-52 bg-white shadow-md`}>
        <span className={`text-7xl sm:text-[5.5rem] font-bold tracking-tight ${c.text} leading-none`}>{score}</span>
        <span className="text-xl sm:text-2xl text-slate-400 font-medium ml-1">/100</span>
      </div>
      <p className="mt-7 text-lg sm:text-xl font-medium text-slate-800 max-w-md leading-snug px-2">
        You are currently losing potential jobs to other {peer} in AI search.
      </p>
    </section>
  );
}

function CategoryBars({ categoryScores }) {
  return (
    <section className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 tracking-tight">Your visibility breakdown</h2>
        <p className="text-sm text-slate-500 mt-1">These factors determine how AI systems rank your business.</p>
      </div>
      <div className="space-y-4">
        {CATEGORY_ORDER.map((key) => {
          const value = categoryScores?.[key] ?? 0;
          const c = scoreColor(value);
          return (
            <div key={key}>
              <div className="flex justify-between items-baseline mb-2">
                <span className="text-sm font-medium text-slate-800">{CATEGORY_LABELS[key]}</span>
                <span className={`text-sm font-semibold tabular-nums ${c.text}`}>{value}%</span>
              </div>
              <div className="h-2.5 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className={`h-full ${c.bar} rounded-full transition-all duration-700`}
                  style={{ width: `${Math.max(2, value)}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function CompetitorTable({ score, competitors }) {
  const aheadCount = (competitors ?? []).filter((c) => c.score > score).length;
  return (
    <section>
      <div className="flex items-baseline justify-between mb-3 gap-3">
        <h2 className="text-lg font-semibold text-slate-900 tracking-tight">Competitor comparison</h2>
        {aheadCount > 0 && (
          <span className="text-xs font-medium text-rose-600 whitespace-nowrap">
            {aheadCount} ahead of you
          </span>
        )}
      </div>
      <div className="rounded-xl border border-slate-200 overflow-hidden bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500 text-[11px] uppercase tracking-wider">
            <tr>
              <th className="text-left px-4 py-3 font-semibold">Business</th>
              <th className="text-right px-4 py-3 font-semibold">Score</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-slate-100 bg-slate-50/40">
              <td className="px-4 py-3.5 font-semibold text-slate-900">You</td>
              <td className="px-4 py-3.5 text-right font-semibold text-slate-900 tabular-nums">{score}</td>
            </tr>
            {(competitors ?? []).map((c) => {
              const beats = c.score > score;
              return (
                <tr key={c.name} className="border-t border-slate-100">
                  <td className="px-4 py-3.5 text-slate-700">{c.name}</td>
                  <td className="px-4 py-3.5 text-right">
                    <span className={`font-semibold tabular-nums ${beats ? "text-rose-600" : "text-slate-700"}`}>
                      {c.score}
                    </span>
                    {beats && (
                      <span className="ml-2 inline-block text-[10px] font-bold uppercase tracking-wider text-rose-700 bg-rose-100 px-1.5 py-0.5 rounded">
                        Ahead
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function GapsSection({ gaps }) {
  const visible = (gaps ?? []).slice(0, 4);
  return (
    <section>
      <h2 className="text-lg font-semibold text-slate-900 tracking-tight mb-1">
        What's causing you to lose visibility
      </h2>
      <p className="text-sm text-slate-500 mb-4">Each gap is sending potential customers to a competitor.</p>
      <ul className="space-y-3">
        {visible.map((g, i) => (
          <li
            key={i}
            className="flex gap-3 items-start rounded-lg bg-rose-50/60 border border-rose-100 px-4 py-3"
          >
            <span className="mt-1.5 shrink-0 w-2 h-2 rounded-full bg-rose-500" />
            <span className="text-[15px] leading-snug text-slate-800">{g}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function PathToTarget({ score, competitors }) {
  const topCompetitorScore = Math.max(score, ...(competitors ?? []).map((c) => c.score));
  const target = Math.min(100, Math.max(topCompetitorScore + 5, score + 20));
  const delta = target - score;
  return (
    <section className="rounded-2xl border border-emerald-100 bg-gradient-to-br from-emerald-50 to-white p-6">
      <div className="flex items-baseline gap-2 mb-2">
        <h2 className="text-lg font-semibold text-slate-900 tracking-tight">Path to {target}</h2>
        <span className="text-xs font-bold uppercase tracking-wider text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded">
          +{delta} pts
        </span>
      </div>
      <p className="text-sm text-slate-700 mb-4">
        A focused 90-day plan to add <span className="font-semibold text-emerald-700">+{delta} points</span> and pass every competitor on this page.
      </p>
      <ol className="space-y-2.5 text-sm text-slate-800">
        {[
          "Fix structured data and schema gaps blocking AI citations",
          "Publish service-area pages targeting the queries competitors win",
          "Build authority signals where competitors currently outrank you",
          "Tune Core Web Vitals and listing health to lock in gains",
        ].map((step, i) => (
          <li key={i} className="flex gap-3 items-start">
            <span className="shrink-0 w-5 h-5 rounded-full bg-emerald-600 text-white text-[11px] font-bold flex items-center justify-center mt-0.5">
              {i + 1}
            </span>
            <span className="leading-snug">{step}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function GrowthProjection({ score }) {
  const projected90 = Math.min(100, score + 22);
  return (
    <section>
      <h2 className="text-lg font-semibold text-slate-900 tracking-tight mb-3">Projected growth</h2>
      <div className="rounded-2xl border border-slate-200 bg-white p-6">
        <div className="flex items-end justify-between gap-4 sm:gap-6">
          <div>
            <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Today</p>
            <p className="text-3xl font-bold text-slate-900 tabular-nums leading-none mt-1">{score}</p>
          </div>
          <div className="flex-1 h-1.5 bg-gradient-to-r from-slate-200 via-emerald-300 to-emerald-500 rounded-full mb-2" />
          <div className="text-right">
            <p className="text-[11px] uppercase tracking-wider text-emerald-700 font-semibold">In 90 days</p>
            <p className="text-3xl font-bold text-emerald-600 tabular-nums leading-none mt-1">{projected90}</p>
          </div>
        </div>
        <p className="text-sm text-slate-600 mt-4 leading-snug">
          Businesses that complete the action plan typically reach this range within one quarter.
        </p>
      </div>
    </section>
  );
}

function ProgramOffer() {
  return (
    <section className="rounded-2xl border border-slate-900 bg-slate-900 text-white p-6">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-2">Done-for-you program</p>
      <h2 className="text-lg font-semibold tracking-tight mb-2">We can run the plan for you</h2>
      <p className="text-sm text-slate-300 leading-snug">
        Our team executes the full plan — citations, schema, content, and reporting — so you can focus on jobs, not algorithms.
      </p>
    </section>
  );
}

function LockedSection({ children }) {
  if (isPaid) {
    return <section className="space-y-8">{children}</section>;
  }

  return (
    <section className="relative rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-sm">
      <div className="p-6 sm:p-8 select-none pointer-events-none blur-[6px] opacity-50 space-y-8">
        {children}
      </div>
      <div className="absolute inset-0 flex items-start justify-center pt-20 sm:pt-24 bg-gradient-to-b from-white/20 via-white/90 to-white">
        <div className="text-center px-6 max-w-md">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-slate-900 text-white text-2xl mb-4 shadow-md">
            🔒
          </div>
          <h3 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight mb-2 leading-tight">
            See exactly how to outrank these competitors
          </h3>
          <p className="text-sm sm:text-base text-slate-600 leading-snug">
            Exact fixes • Where they beat you • Step-by-step improvements
          </p>
        </div>
      </div>
    </section>
  );
}

function StripeCTA() {
  if (isPaid) {
    return (
      <div className="text-center mt-6">
        <span className="inline-flex items-center gap-2 text-emerald-700 bg-emerald-50 border border-emerald-200 px-4 py-2 rounded-full text-sm font-semibold">
          ✅ Full report unlocked
        </span>
      </div>
    );
  }

  return (
    <section className="text-center pt-2">
      <a
        href={STRIPE_CHECKOUT_URL}
        className="inline-block w-full sm:w-auto bg-slate-900 hover:bg-slate-800 active:bg-black text-white font-semibold text-base sm:text-lg px-8 py-4 rounded-xl shadow-lg shadow-slate-900/20 transition-all hover:shadow-xl hover:-translate-y-0.5"
      >
        See who's taking your jobs — $99
      </a>
      <p className="mt-4 text-xs sm:text-sm text-slate-500">
        One-time payment · Instant access · No subscription
      </p>
    </section>
  );
}

export default function ResultsPage({ data }) {
  if (!data) return null;
  const { score, category_scores, gaps, competitors, trade } = data;

  return (
    <main className="min-h-screen bg-gradient-to-b from-slate-50 to-white">
      <div className="max-w-2xl mx-auto px-4 sm:px-6 pb-20">
        <HeroScore score={score} trade={trade} />

        <div className="mt-4 sm:mt-6">
          <LockedSection>
            <CategoryBars categoryScores={category_scores} />
            <CompetitorTable score={score} competitors={competitors} />
            <GapsSection gaps={gaps} />
            <PathToTarget score={score} competitors={competitors} />
            <GrowthProjection score={score} />
            <ProgramOffer />
          </LockedSection>
        </div>

        <div className="mt-8">
          <StripeCTA />
        </div>
      </div>
    </main>
  );
}
