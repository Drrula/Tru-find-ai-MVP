import React, { useEffect, useState } from "react";
import ResultsPage from "../ResultsPage.jsx";
import { apiFetch, ApiError } from "./lib/api.js";

const STORAGE_KEY = "trufindai:lastAnalysis";

export default function App() {
  const [businessName, setBusinessName] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [location, setLocation] = useState("");
  const [data, setData] = useState(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (data) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
      } catch {}
    }
  }, [data]);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      // /analyze-business is the back-compat alias preserved through Phase B
      // per ADR-005. When async-with-poll /v1/analyses ships in Phase C,
      // this single call site migrates and the rest of the app is unaffected.
      const json = await apiFetch("/analyze-business", {
        method: "POST",
        body: JSON.stringify({
          business_name: businessName.trim(),
          location: location.trim(),
          website_url: websiteUrl.trim() || null,
        }),
      });
      setData(json);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.requestId
            ? `${err.message} (request: ${err.requestId})`
            : err.message,
        );
      } else {
        setError(err?.message ?? "Failed to load results.");
      }
    } finally {
      setLoading(false);
    }
  }

  if (data) return <ResultsPage data={data} />;

  return (
    <main className="min-h-screen bg-gradient-to-b from-slate-50 to-white flex items-center justify-center px-4 sm:px-5 py-12 sm:py-16">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md bg-white rounded-2xl border border-slate-200 shadow-md p-6 sm:p-8 space-y-5"
      >
        <div className="text-center sm:text-left">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 mb-2">
            TruFindAI
          </p>
          <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight leading-tight">
            Scan your AI visibility
          </h1>
          <p className="text-sm sm:text-base text-slate-600 mt-2 leading-snug">
            See exactly where you stand in AI search results — and who's taking your jobs.
          </p>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-sm font-semibold text-slate-800">Business name</label>
            <input
              value={businessName}
              onChange={(e) => setBusinessName(e.target.value)}
              required
              placeholder="Acme Roofing"
              className="mt-1.5 w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-[15px] focus:outline-none focus:ring-2 focus:ring-slate-900 focus:border-slate-900 transition-colors"
            />
          </div>

          <div>
            <label className="text-sm font-semibold text-slate-800">Website URL</label>
            <input
              type="url"
              value={websiteUrl}
              onChange={(e) => setWebsiteUrl(e.target.value)}
              placeholder="https://example.com"
              className="mt-1.5 w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-[15px] focus:outline-none focus:ring-2 focus:ring-slate-900 focus:border-slate-900 transition-colors"
            />
          </div>

          <div>
            <label className="text-sm font-semibold text-slate-800">Location / market</label>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              required
              placeholder="Miami, FL"
              className="mt-1.5 w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-[15px] focus:outline-none focus:ring-2 focus:ring-slate-900 focus:border-slate-900 transition-colors"
            />
          </div>
        </div>

        {error && (
          <p className="text-sm text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-slate-900 hover:bg-slate-800 active:bg-black disabled:opacity-50 text-white font-semibold text-base px-5 py-3.5 rounded-xl shadow-md shadow-slate-900/20 transition-all hover:shadow-lg disabled:hover:shadow-md"
        >
          {loading ? "Scanning…" : "Scan my business"}
        </button>
      </form>
    </main>
  );
}
