import { useEffect, useState } from 'react';

const RELEASES_API = 'https://api.github.com/repos/AnitChaudhry/HRKit/releases/latest';
const FALLBACK = '1.0.0';
const CACHE_KEY = 'hrkit-latest-version';
const CACHE_TTL_MS = 60 * 60 * 1000;

type Cached = { version: string; ts: number };

function readCache(): string | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Cached;
    if (Date.now() - parsed.ts > CACHE_TTL_MS) return null;
    return parsed.version;
  } catch {
    return null;
  }
}

function writeCache(version: string) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ version, ts: Date.now() }));
  } catch {
    // ignore
  }
}

export function useLatestVersion(): string {
  const [version, setVersion] = useState<string>(() => readCache() ?? FALLBACK);

  useEffect(() => {
    const controller = new AbortController();
    fetch(RELEASES_API, { signal: controller.signal, headers: { Accept: 'application/vnd.github+json' } })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`status ${r.status}`))))
      .then((data: { tag_name?: string }) => {
        const tag = (data?.tag_name ?? '').replace(/^v/, '').trim();
        if (tag) {
          setVersion(tag);
          writeCache(tag);
        }
      })
      .catch(() => {
        // network error / rate limit — keep fallback or cached value
      });
    return () => controller.abort();
  }, []);

  return version;
}
