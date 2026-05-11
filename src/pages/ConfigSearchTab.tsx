import React, { useCallback, useState } from 'react';
import { RotateCcw, Search, Server } from 'lucide-react';
import PageHero from '../components/PageHero';

interface ConfigSearchMatch {
  line: number;
  content: string;
}

interface ConfigSearchResult {
  snapshot_id: string;
  hostname: string;
  ip_address: string;
  vendor?: string;
  platform?: string;
  snapshot_time?: string;
  total_matches: number;
  matches: ConfigSearchMatch[];
}

interface ConfigSearchTabProps {
  t: (key: string) => string;
}

const presetKeywords = ['192.168', '10.0.0', 'vlan', 'ospf', 'bgp', 'acl', 'interface', 'route-static', 'ntp', 'snmp'];

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const ConfigSearchTab: React.FC<ConfigSearchTabProps> = ({ t }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<ConfigSearchResult[]>([]);
  const [loading, setLoading] = useState(false);

  const runSearch = useCallback(async (rawQuery?: string) => {
    const nextQuery = (rawQuery ?? query).trim();
    if (nextQuery.length < 2) return;

    setLoading(true);
    try {
      const resp = await fetch(`/api/configs/search?q=${encodeURIComponent(nextQuery)}`);
      if (resp.ok) {
        const data = await resp.json();
        setResults(Array.isArray(data) ? data : []);
      }
    } catch {
      // ignore search request errors and preserve the current view
    } finally {
      setLoading(false);
    }
  }, [query]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <PageHero
        icon={Search}
        title={t('configSearchTab')}
        subtitle={t('globalConfigSearchDesc')}
      />

      <div className="flex-1 flex flex-col overflow-hidden px-6 py-5">
      <div className="flex-1 bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden flex flex-col">
        <div className="p-5 border-b border-black/5 bg-black/[0.01]">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-black/30" size={15} />
              <input
                autoFocus
                type="text"
                placeholder="e.g.  192.168.1.1  |  10.0.0.0/24  |  vlan 100  |  ospf  |  bgp 65001"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    void runSearch();
                  }
                }}
                className="w-full pl-10 pr-3 py-2.5 border border-black/10 rounded-xl text-sm font-mono focus:border-[#00bceb]/50 outline-none transition-all"
              />
            </div>
            <button
              onClick={() => void runSearch()}
              disabled={loading || query.trim().length < 2}
              className="px-5 py-2 bg-[#00bceb] text-white rounded-xl text-xs font-bold hover:bg-[#0096bd] transition-all disabled:opacity-50"
            >
              {loading ? <RotateCcw size={14} className="animate-spin" /> : <Search size={14} />}
            </button>
          </div>
          <div className="flex gap-1.5 mt-2">
            {presetKeywords.map((keyword) => (
              <button
                key={keyword}
                onClick={() => setQuery(keyword)}
                className="px-2.5 py-1 text-[10px] font-bold bg-black/5 hover:bg-black/10 rounded-lg transition-all"
              >
                {keyword}
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-auto p-5 space-y-3">
          {query.trim() === '' && results.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-black/20 text-center">
              <Search size={36} strokeWidth={1} />
              <p className="mt-3 text-sm font-medium">{t('globalSearchHint')}</p>
              <p className="text-xs mt-1 text-black/30 max-w-md">{t('globalSearchHintDesc')}</p>
            </div>
          ) : loading ? (
            <div className="h-full flex flex-col items-center justify-center text-black/30">
              <RotateCcw size={28} className="animate-spin mb-3" />
              <p className="text-sm">{t('searching')}...</p>
            </div>
          ) : results.length === 0 && query.trim().length >= 2 ? (
            <div className="text-black/30 text-center py-16 text-sm">{t('noMatchesFound')} "{query}"</div>
          ) : (
            <>
              {results.length > 0 && (
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-xs font-bold text-black/50">
                    {results.length} {t('devicesMatched')} · {results.reduce((sum, result) => sum + result.total_matches, 0)} {t('totalMatches')}
                  </span>
                </div>
              )}
              {results.map((result) => {
                const normalizedQuery = query.toLowerCase().trim();
                const highlightPattern = new RegExp(`(${escapeRegExp(normalizedQuery)})`, 'gi');
                return (
                  <div key={result.snapshot_id} className="rounded-xl border border-black/5 overflow-hidden">
                    <div className="flex items-center justify-between px-4 py-2.5 bg-black/[0.02] border-b border-black/5">
                      <div className="flex items-center gap-2">
                        <Server size={13} className="text-black/30" />
                        <span className="text-xs font-bold">{result.hostname}</span>
                        <span className="text-[10px] text-black/30 font-mono">{result.ip_address}</span>
                        {result.vendor && <span className="text-[9px] px-1.5 py-0.5 bg-black/5 rounded text-black/40">{result.vendor}</span>}
                        {result.platform && <span className="text-[9px] px-1.5 py-0.5 bg-black/5 rounded text-black/40">{result.platform}</span>}
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[9px] text-black/30">{result.snapshot_time ? new Date(result.snapshot_time).toLocaleString() : ''}</span>
                        <span className="text-[9px] font-bold bg-[#00bceb]/10 text-[#00bceb] px-2 py-0.5 rounded-full">
                          {result.total_matches} match{result.total_matches > 1 ? 'es' : ''}
                        </span>
                      </div>
                    </div>
                    <div className="bg-[#1E1E1E] font-mono text-xs">
                      {result.matches.slice(0, 12).map((match) => (
                        <div key={match.line} className="flex items-start px-4 py-1 hover:bg-white/5">
                          <span className="w-10 text-right text-white/20 pr-4 select-none flex-shrink-0">{match.line}</span>
                          <span className="text-[#d4d4d4] whitespace-pre">
                            {match.content.split(highlightPattern).map((part, index) => (
                              part.toLowerCase() === normalizedQuery
                                ? <mark key={`${match.line}-${index}`} className="bg-[#00bceb]/30 text-[#00bceb] rounded px-0.5">{part}</mark>
                                : <React.Fragment key={`${match.line}-${index}`}>{part}</React.Fragment>
                            ))}
                          </span>
                        </div>
                      ))}
                      {result.total_matches > 12 && (
                        <div className="px-4 py-1 text-white/20 text-[10px]">... and {result.total_matches - 12} {t('moreLines')}</div>
                      )}
                    </div>
                  </div>
                );
              })}
            </>
          )}
        </div>
      </div>
      </div>
    </div>
  );
};

export default ConfigSearchTab;