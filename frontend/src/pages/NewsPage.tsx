import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ApiError } from '../services/api';
import { newsService } from '../services/newsService';
import type { NewsArticle, NewsFeedResponse, NewsInstrumentCandidate } from '../services/newsService';
import { getDefaultNewsDateRange, isCalendarDate, isValidNewsDateRange } from '../services/newsDateRange';
import { Button } from '../components/common/Button';
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
          className="h-[72px] w-[104px] shrink-0 rounded-md border border-terminal-border object-cover sm:h-[82px] sm:w-[124px]"
        />
      ) : null}
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-terminal-muted">
          <span>{article.publisher || 'Yahoo Finance'}</span>
          <span aria-hidden="true">·</span>
          <time dateTime={article.published_at ?? undefined}>{timeLabel(article.published_at)}</time>
        </div>
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-semibold leading-5 text-terminal-text decoration-terminal-accent/60 underline-offset-4 group-hover:text-white group-hover:underline"
          >
            {article.title}
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        ) : (
          <h2 className="text-sm font-semibold leading-5 text-terminal-text">{article.title}</h2>
        )}
        {article.summary ? (
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-terminal-muted">{article.summary}</p>
        ) : null}
        {article.related_symbols.length ? (
          <div className="mt-2 flex flex-wrap gap-1">
            {article.related_symbols.slice(0, 6).map((symbol) => (
              <span
                key={symbol}
                className="rounded border border-terminal-border bg-terminal-panelAlt px-1.5 py-0.5 text-2xs text-terminal-muted"
              >
                {symbol}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open original article: ${article.title}`}
          className="mt-0.5 hidden h-8 w-8 shrink-0 items-center justify-center rounded-md text-terminal-muted transition-colors hover:bg-white/[0.05] hover:text-terminal-accent sm:flex"
        >
          <Icon name="external" size={14} />
        </a>
      ) : null}
    </article>
  );
}

const dateInputClass =
  'h-9 w-[148px] rounded-md border border-terminal-border bg-terminal-panelAlt px-2.5 text-xs text-terminal-text ' +
  'transition-colors focus:border-terminal-accent focus:outline-none focus:ring-1 focus:ring-terminal-accent';

export function NewsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get('news_instrument_id') ?? '';
  const selectedSymbol = searchParams.get('news_symbol') ?? '';
  const [searchText, setSearchText] = useState('');
  const [suggestions, setSuggestions] = useState<NewsInstrumentCandidate[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [initialDateRange] = useState(() => {
    const dateFrom = searchParams.get('news_date_from') ?? '';
    const dateTo = searchParams.get('news_date_to') ?? '';
    return isCalendarDate(dateFrom) && isCalendarDate(dateTo)
      ? { dateFrom, dateTo }
      : getDefaultNewsDateRange();
  });
  const [dateFrom, setDateFrom] = useState(initialDateRange.dateFrom);
  const [dateTo, setDateTo] = useState(initialDateRange.dateTo);
  const [feed, setFeed] = useState<NewsFeedResponse | null>(null);
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [canLoadMore, setCanLoadMore] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const dateRangeError = !isValidNewsDateRange(dateFrom, dateTo)
    ? 'Start date must be on or before the end date.'
    : null;

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
    let active = true;
    const pageSize = 20;
    setError(null);
    if (dateRangeError) {
      setFeed(null);
      setArticles([]);
      setCanLoadMore(false);
      setLoading(false);
      return () => { active = false; };
    }
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
      ? newsService.symbolFeed(selectedId, selectedSymbol, { page, pageSize, dateFrom, dateTo })
      : newsService.generalFeed({ page, pageSize, dateFrom, dateTo });
    void request.then((result) => {
      if (!active) return;
      setFeed(result);
      setArticles((current) => page === 1 ? result.items : [...current, ...result.items]);
      setCanLoadMore(page * pageSize < result.count);
      setError(null);
    }).catch((caught: unknown) => {
      if (!active) return;
      setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : 'News could not be loaded.');
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [selectedId, selectedSymbol, dateFrom, dateTo, dateRangeError, page, reloadToken]);

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

  function updateDateRange(field: 'news_date_from' | 'news_date_to', value: string) {
    setPage(1);
    if (field === 'news_date_from') setDateFrom(value);
    else setDateTo(value);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (value) next.set(field, value);
      else next.delete(field);
      return next;
    });
  }

  return (
    <div className="w-full min-w-0 px-4 py-4 lg:px-6 text-terminal-text">
      <header className="mb-4 border-b border-terminal-border pb-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <p className="mb-1 text-2xs font-semibold uppercase tracking-[0.22em] text-terminal-accent">
              Yahoo Finance · News Intelligence
            </p>
            <h1 className="text-xl font-semibold tracking-tight text-terminal-text">News</h1>
            <p className="mt-1 max-w-2xl text-xs text-terminal-muted">
              Company and instrument headlines from Yahoo Finance, with original publisher links.
            </p>
          </div>
          <div className="text-right text-2xs text-terminal-muted">
            <div>
              {feed?.last_updated
                ? `Updated ${timeLabel(feed.last_updated)}`
                : feed?.last_successful_refresh
                  ? `Updated ${timeLabel(feed.last_successful_refresh)}`
                  : 'Waiting for Yahoo Finance cache'}
            </div>
            {feed?.stale ? <div className="mt-1 text-terminal-amber">Showing cached / refreshing data</div> : null}
          </div>
        </div>

        <div className="mt-4 grid items-end gap-2 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div className="relative">
            <label className="sr-only" htmlFor="news-instrument-search">Search supported instruments</label>
            <div className="flex h-9 items-center gap-2 rounded-md border border-terminal-border bg-terminal-panelAlt px-2.5 transition-colors focus-within:border-terminal-accent focus-within:ring-1 focus-within:ring-terminal-accent">
              <Icon name="search" size={14} className="shrink-0 text-terminal-muted" />
              <input
                id="news-instrument-search"
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Escape') {
                    setSuggestions([]);
                    setSearchError(null);
                  }
                }}
                placeholder="Search ticker or company · AAPL, RELIANCE.NS, BTC-USD"
                autoComplete="off"
                className="min-w-0 flex-1 bg-transparent text-xs text-terminal-text outline-none placeholder:text-terminal-muted/70"
                role="combobox"
                aria-autocomplete="list"
                aria-expanded={suggestions.length > 0}
                aria-controls="news-search-results"
              />
              {searching ? <span className="shrink-0 text-2xs text-terminal-muted">Searching…</span> : null}
              {searchText ? (
                <button
                  type="button"
                  onClick={clearSearch}
                  aria-label="Clear search"
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-terminal-muted transition-colors hover:bg-white/[0.06] hover:text-terminal-text"
                >
                  <Icon name="close" size={13} />
                </button>
              ) : null}
            </div>
            {suggestions.length > 0 ? (
              <div
                id="news-search-results"
                role="listbox"
                className="absolute z-40 mt-1.5 max-h-80 w-full overflow-y-auto rounded-md border border-terminal-border bg-terminal-panel p-1 shadow-xl"
              >
                {suggestions.map((candidate) => (
                  <button
                    key={candidate.instrument_id}
                    type="button"
                    role="option"
                    aria-selected={false}
                    onClick={() => selectInstrument(candidate)}
                    className="flex w-full items-center justify-between gap-3 rounded px-2.5 py-2 text-left transition-colors hover:bg-white/[0.05]"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-semibold text-terminal-text">{candidate.name}</span>
                      <span className="mt-0.5 block truncate text-2xs text-terminal-muted">
                        {candidate.symbol} · {candidate.exchange} · {candidate.instrument_type}
                      </span>
                    </span>
                    <span className="shrink-0 rounded border border-terminal-border bg-terminal-panelAlt px-1.5 py-0.5 text-2xs text-terminal-accent">
                      {candidate.market}
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
            {searchError ? <p role="status" className="mt-1 px-1 text-2xs text-terminal-amber">{searchError}</p> : null}
            {searchText.trim() && !searching && !searchError && suggestions.length === 0 ? (
              <p role="status" className="mt-1 px-1 text-2xs text-terminal-muted">
                No matching Yahoo Finance listings are supported by Tradely.
              </p>
            ) : null}
          </div>

          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-2xs font-medium text-terminal-muted">
              From
              <input
                aria-label="Filter from date"
                type="date"
                value={dateFrom}
                onChange={(event) => updateDateRange('news_date_from', event.target.value)}
                className={dateInputClass}
              />
            </label>
            <label className="flex flex-col gap-1 text-2xs font-medium text-terminal-muted">
              To
              <input
                aria-label="Filter to date"
                type="date"
                value={dateTo}
                onChange={(event) => updateDateRange('news_date_to', event.target.value)}
                className={dateInputClass}
              />
            </label>
          </div>
        </div>
      </header>

      {selectedId ? (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-terminal-border bg-terminal-panel px-3 py-2.5">
          <div className="min-w-0">
            <div className="text-2xs font-semibold uppercase tracking-[0.18em] text-terminal-muted">Selected instrument</div>
            <div className="mt-0.5 truncate text-sm font-semibold text-terminal-text">
              {heading}
              <span className="ml-1 text-xs font-medium text-terminal-accent">{selectedSymbol}</span>
            </div>
            <div className="mt-0.5 text-2xs text-terminal-muted">
              {selectedInstrument?.exchange || feed?.exchange || ''} · Yahoo symbol {feed?.yahoo_symbol || selectedSymbol}
            </div>
          </div>
          <Button size="sm" variant="secondary" onClick={clearSelection}>
            Back to general feed
          </Button>
        </div>
      ) : (
        <div className="mb-3 flex items-start gap-2 text-2xs leading-relaxed text-terminal-muted">
          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-terminal-accent" />
          {feed?.coverage || 'The feed aggregates cached Yahoo Finance headlines for the watchlist and instruments previously searched or analyzed; it is not market-wide.'}
        </div>
      )}

      <section className="panel-surface px-3 sm:px-4" aria-label="Yahoo Finance news articles">
        {dateRangeError ? (
          <div role="alert" className="py-12 text-center text-sm text-terminal-amber">{dateRangeError}</div>
        ) : loading && articles.length === 0 ? (
          <div aria-label="Loading news" className="space-y-3 py-4">
            {[1, 2, 3, 4].map((item) => (
              <div key={item} className="flex gap-3 border-b border-terminal-borderSoft pb-3">
                <div className="skeleton-block h-[72px] w-[104px] rounded-md" />
                <div className="flex-1 space-y-2 py-1">
                  <div className="skeleton-block h-2 w-1/4" />
                  <div className="skeleton-block h-4 w-4/5" />
                  <div className="skeleton-block h-3 w-2/3" />
                </div>
              </div>
            ))}
          </div>
        ) : error && articles.length === 0 ? (
          <div role="alert" className="py-12 text-center">
            <p className="text-sm font-medium text-terminal-text">News could not be loaded</p>
            <p className="mt-1 text-xs text-terminal-muted">{error}</p>
            <Button
              className="mt-3"
              size="sm"
              variant="secondary"
              icon="refresh"
              onClick={() => { setPage(1); setFeed(null); setReloadToken((value) => value + 1); }}
            >
              Retry
            </Button>
          </div>
        ) : articles.length === 0 ? (
          <div className="py-12 text-center">
            <p className="text-sm font-medium text-terminal-text">No cached headlines yet</p>
            <p className="mt-1 text-xs text-terminal-muted">
              Yahoo Finance may not have ticker-specific coverage for this instrument. Check back after the background refresh.
            </p>
            {selectedId ? (
              <Button
                className="mt-3"
                size="sm"
                variant="secondary"
                icon="refresh"
                onClick={() => { setPage(1); setFeed(null); setReloadToken((value) => value + 1); }}
              >
                Retry
              </Button>
            ) : null}
          </div>
        ) : (
          <>
            {error ? (
              <div role="status" className="border-b border-terminal-border py-2 text-xs text-terminal-amber">
                Showing previously cached headlines. Refresh issue: {error}
              </div>
            ) : null}
            {articles.map((article) => <ArticleRow key={article.id} article={article} />)}
            {canLoadMore ? (
              <div className="flex justify-center py-4">
                <Button
                  variant="secondary"
                  loading={loading}
                  onClick={() => setPage((current) => current + 1)}
                >
                  Load more headlines
                </Button>
              </div>
            ) : null}
          </>
        )}
      </section>
      <p className="mt-3 text-2xs leading-relaxed text-terminal-muted">
        Headlines and excerpts are supplied by Yahoo Finance and their publishers. Article links open the original publisher page; Tradely does not reproduce full articles.
      </p>
    </div>
  );
}
