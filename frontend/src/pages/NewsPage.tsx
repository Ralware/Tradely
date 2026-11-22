import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ApiError } from '../services/api';
import { newsService } from '../services/newsService';
import type { NewsArticle, NewsFeedResponse, NewsInstrumentCandidate } from '../services/newsService';
import { Icon } from '../components/common/Icon';

function timeLabel(value: string | null): string {
  if (!value) return 'Publication time unavailable';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Publication time unavailable';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function safeArticleHref(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}

function ArticleRow({ article }: { article: NewsArticle }) {
  const href = safeArticleHref(article.article_url);
  return (
    <article className="group flex gap-3 border-b border-terminal-borderSoft py-3 last:border-b-0">
      {article.thumbnail_url ? (
        <img
          src={article.thumbnail_url}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          className="h-[72px] w-[104px] shrink-0 rounded-lg border border-terminal-border object-cover sm:h-[82px] sm:w-[124px]"
        />
      ) : null}
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-terminal-muted">
          <span>{article.publisher || 'Yahoo Finance'}</span>
          <span aria-hidden="true">·</span>
          <time dateTime={article.published_at ?? undefined}>{timeLabel(article.published_at)}</time>
        </div>
        {href ? (
          <a href={href} target="_blank" rel="noopener noreferrer" className="text-sm font-semibold leading-5 text-terminal-text decoration-terminal-accent/60 underline-offset-4 group-hover:text-white group-hover:underline">
            {article.title}<span className="sr-only"> (opens in a new tab)</span>
          </a>
        ) : <h2 className="text-sm font-semibold leading-5 text-terminal-text">{article.title}</h2>}
        {article.summary ? <p className="mt-1 line-clamp-2 text-xs leading-5 text-terminal-muted">{article.summary}</p> : null}
        {article.related_symbols.length ? (
          <div className="mt-2 flex flex-wrap gap-1">
            {article.related_symbols.slice(0, 6).map((symbol) => (
              <span key={symbol} className="rounded-full border border-terminal-border px-2 py-0.5 text-[9px] text-terminal-muted">{symbol}</span>
            ))}
          </div>
        ) : null}
      </div>
      {href ? <a href={href} target="_blank" rel="noopener noreferrer" aria-label={`Open original article: ${article.title}`} className="mt-0.5 hidden h-8 w-8 shrink-0 items-center justify-center rounded-full text-terminal-muted hover:bg-white/[0.05] hover:text-terminal-accent sm:flex"><Icon name="external" size={14} /></a> : null}
    </article>
  );
}

export function NewsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get('news_instrument_id') ?? '';
  const selectedSymbol = searchParams.get('news_symbol') ?? '';
  const [searchText, setSearchText] = useState('');
  const [suggestions, setSuggestions] = useState<NewsInstrumentCandidate[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [feed, setFeed] = useState<NewsFeedResponse | null>(null);
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [canLoadMore, setCanLoadMore] = useState(false);

  useEffect(() => {
    const value = searchText.trim();
    if (!value) {
      setSuggestions([]);
      setSearching(false);
      setSearchError(null);
      return undefined;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearching(true);
      setSearchError(null);
      void newsService.search(value, controller.signal)
        .then((result) => setSuggestions(result.items))
        .catch((caught: unknown) => {
          if (controller.signal.aborted) return;
          setSuggestions([]);
          setSearchError(caught instanceof Error ? caught.message : 'Instrument search failed.');
        })
        .finally(() => { if (!controller.signal.aborted) setSearching(false); });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [searchText]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const pageSize = 20;
    setError(null);
    const cached = selectedId && selectedSymbol
      ? newsService.cachedSymbol(selectedId, page, pageSize, { dateFrom, dateTo })
      : !selectedId ? newsService.cachedGeneral({ page, pageSize, dateFrom, dateTo }) : undefined;
    if (cached && page === 1) {
      setFeed(cached);
      setArticles(cached.items);
      setLoading(false);
    } else if (page === 1) {
      setLoading(true);
      setArticles([]);
    } else {
      setLoading(false);
    }
    const request = selectedId && selectedSymbol
      ? newsService.symbolFeed(selectedId, selectedSymbol, { page, pageSize, dateFrom, dateTo, signal: controller.signal })
      : newsService.generalFeed({ page, pageSize, dateFrom, dateTo, signal: controller.signal });
    void request.then((result) => {
      if (!active) return;
      setFeed(result);
      setArticles((current) => page === 1 ? result.items : [...current, ...result.items]);
      setCanLoadMore(page * pageSize < result.count);
      setError(null);
    }).catch((caught: unknown) => {
      if (!active || controller.signal.aborted) return;
      setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : 'News could not be loaded.');
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [selectedId, selectedSymbol, dateFrom, dateTo, page]);

  const selectedInstrument = feed?.instrument;
  const heading = useMemo(() => selectedInstrument?.name || selectedSymbol || 'Market feed', [selectedInstrument?.name, selectedSymbol]);

  function selectInstrument(candidate: NewsInstrumentCandidate) {
    setSearchText('');
    setSuggestions([]);
    setPage(1);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set('news_instrument_id', candidate.instrument_id);
      next.set('news_symbol', candidate.symbol);
      return next;
    });
  }

  function clearSelection() {
    setPage(1);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete('news_instrument_id');
      next.delete('news_symbol');
      return next;
    });
  }

  function clearSearch() {
    setSearchText('');
    setSuggestions([]);
    setSearchError(null);
  }

  return (
    <div className="min-h-full bg-black px-4 py-5 text-terminal-text sm:px-6 lg:px-8">
      <header className="mb-5 border-b border-terminal-border pb-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-terminal-accent">Yahoo Finance · News Intelligence</p>
            <h1 className="text-xl font-semibold tracking-tight text-white">News</h1>
            <p className="mt-1 max-w-2xl text-xs text-terminal-muted">Company and instrument headlines from Yahoo Finance, with original publisher links.</p>
          </div>
          <div className="text-right text-[10px] text-terminal-muted">
            <div>{feed?.last_updated ? `Updated ${timeLabel(feed.last_updated)}` : feed?.last_successful_refresh ? `Updated ${timeLabel(feed.last_successful_refresh)}` : 'Waiting for Yahoo Finance cache'}</div>
            {feed?.stale ? <div className="mt-1 text-amber-300">Showing cached / refreshing data</div> : null}
          </div>
        </div>
        <div className="mt-4 grid gap-2 md:grid-cols-[minmax(280px,1fr)_auto]">
          <div className="relative">
            <label className="sr-only" htmlFor="news-instrument-search">Search supported instruments</label>
            <div className="flex h-10 items-center gap-2 rounded-full border border-terminal-border bg-[#050505] px-3 focus-within:border-terminal-accent/70">
              <Icon name="search" size={15} className="text-terminal-muted" />
              <input id="news-instrument-search" value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search ticker or company · AAPL, RELIANCE.NS, BTC-USD" autoComplete="off" className="min-w-0 flex-1 bg-transparent text-xs text-terminal-text outline-none placeholder:text-terminal-muted/70" aria-expanded={suggestions.length > 0} aria-controls="news-search-results" />
              {searching ? <span className="text-[10px] text-terminal-muted">Searching…</span> : null}
              {searchText ? <button type="button" onClick={clearSearch} aria-label="Clear search" className="rounded-full p-1 text-terminal-muted hover:text-white"><Icon name="close" size={13} /></button> : null}
            </div>
            {suggestions.length > 0 ? (
              <div id="news-search-results" role="listbox" className="absolute z-40 mt-2 max-h-80 w-full overflow-y-auto rounded-2xl border border-terminal-border bg-[#080808] p-1 shadow-2xl">
                {suggestions.map((candidate) => (
                  <button key={candidate.instrument_id} type="button" role="option" aria-selected={false} onClick={() => selectInstrument(candidate)} className="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-left hover:bg-white/[0.05]">
                    <span className="min-w-0"><span className="block truncate text-xs font-semibold text-white">{candidate.name}</span><span className="mt-0.5 block truncate text-[10px] text-terminal-muted">{candidate.symbol} · {candidate.exchange} · {candidate.instrument_type}</span></span>
                    <span className="shrink-0 rounded-full border border-terminal-border px-2 py-1 text-[9px] text-terminal-accent">{candidate.market}</span>
                  </button>
                ))}
              </div>
            ) : null}
            {searchError ? <p role="status" className="mt-1 px-3 text-[10px] text-amber-300">{searchError}</p> : null}
            {searchText.trim() && !searching && !searchError && suggestions.length === 0 ? <p role="status" className="mt-1 px-3 text-[10px] text-terminal-muted">No matching Yahoo Finance listings are supported by Tradely.</p> : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex h-10 items-center gap-2 rounded-full border border-terminal-border bg-[#050505] px-3 text-[10px] text-terminal-muted">From<input aria-label="Filter from date" type="date" value={dateFrom} onChange={(event) => { setPage(1); setDateFrom(event.target.value); }} className="max-w-[126px] bg-transparent text-[10px] text-terminal-text outline-none" /></label>
            <label className="flex h-10 items-center gap-2 rounded-full border border-terminal-border bg-[#050505] px-3 text-[10px] text-terminal-muted">To<input aria-label="Filter to date" type="date" value={dateTo} onChange={(event) => { setPage(1); setDateTo(event.target.value); }} className="max-w-[126px] bg-transparent text-[10px] text-terminal-text outline-none" /></label>
          </div>
        </div>
      </header>

      {selectedId ? (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-terminal-border bg-[#050505] px-4 py-3">
          <div className="min-w-0"><div className="text-[9px] font-semibold uppercase tracking-[0.18em] text-terminal-muted">Selected instrument</div><div className="mt-0.5 truncate text-sm font-semibold text-white">{heading} <span className="ml-1 text-xs font-medium text-terminal-accent">{selectedSymbol}</span></div><div className="mt-0.5 text-[10px] text-terminal-muted">{selectedInstrument?.exchange || feed?.exchange || ''} · Yahoo symbol {feed?.yahoo_symbol || selectedSymbol}</div></div>
          <button type="button" onClick={clearSelection} className="rounded-full border border-terminal-border px-3 py-1.5 text-[10px] text-terminal-muted hover:border-terminal-accent/50 hover:text-white">Back to general feed</button>
        </div>
      ) : (
        <div className="mb-3 flex items-center gap-2 text-[10px] text-terminal-muted"><span className="h-1.5 w-1.5 rounded-full bg-terminal-accent" />{feed?.coverage || 'The feed aggregates cached Yahoo Finance headlines for the watchlist and instruments previously searched or analyzed; it is not market-wide.'}</div>
      )}

      <section className="rounded-2xl border border-terminal-border bg-[#030303] px-3 sm:px-5" aria-label="Yahoo Finance news articles">
        {loading && articles.length === 0 ? (
          <div aria-label="Loading news" className="space-y-3 py-4">{[1, 2, 3, 4].map((item) => <div key={item} className="flex gap-3 border-b border-terminal-borderSoft pb-3"><div className="skeleton-block h-[72px] w-[104px] rounded-lg" /><div className="flex-1 space-y-2 py-1"><div className="skeleton-block h-2 w-1/4" /><div className="skeleton-block h-4 w-4/5" /><div className="skeleton-block h-3 w-2/3" /></div></div>)}</div>
        ) : error && articles.length === 0 ? (
          <div role="alert" className="py-12 text-center"><p className="text-sm font-medium text-white">News could not be loaded</p><p className="mt-1 text-xs text-terminal-muted">{error}</p><button type="button" onClick={() => { setPage(1); setFeed(null); }} className="mt-3 rounded-full border border-terminal-border px-3 py-1.5 text-xs text-terminal-text hover:border-terminal-accent">Retry</button></div>
        ) : articles.length === 0 ? (
          <div className="py-12 text-center"><p className="text-sm font-medium text-white">No cached headlines yet</p><p className="mt-1 text-xs text-terminal-muted">Yahoo Finance may not have ticker-specific coverage for this instrument. Check back after the background refresh.</p>{selectedId ? <button type="button" onClick={() => { setPage(1); setFeed(null); }} className="mt-3 rounded-full border border-terminal-border px-3 py-1.5 text-xs text-terminal-text hover:border-terminal-accent">Retry</button> : null}</div>
        ) : (
          <>
            {error ? <div role="status" className="border-b border-terminal-border py-2 text-xs text-amber-300">Showing previously cached headlines. Refresh issue: {error}</div> : null}
            {articles.map((article) => <ArticleRow key={article.id} article={article} />)}
            {canLoadMore ? <div className="flex justify-center py-4"><button type="button" disabled={loading} onClick={() => setPage((current) => current + 1)} className="rounded-full border border-terminal-border px-4 py-2 text-xs text-terminal-text hover:border-terminal-accent disabled:opacity-50">{loading ? 'Loading…' : 'Load more headlines'}</button></div> : null}
          </>
        )}
      </section>
      <p className="mt-3 text-[9px] leading-4 text-terminal-muted">Headlines and excerpts are supplied by Yahoo Finance and their publishers. Article links open the original publisher page; Tradely does not reproduce full articles.</p>
    </div>
  );
}
