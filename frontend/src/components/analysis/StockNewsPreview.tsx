import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { newsService } from '../../services/newsService';
import type { NewsArticle, NewsFeedResponse } from '../../services/newsService';
import { Button } from '../common/Button';
import { Icon } from '../common/Icon';

function publishedLabel(value: string | null): string {
  if (!value) return 'Time unavailable';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? 'Time unavailable'
    : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date);
}

export function StockNewsPreview({ instrumentId, symbol }: { instrumentId: string; symbol: string }) {
  const navigate = useNavigate();
  const [feed, setFeed] = useState<NewsFeedResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(false);
    void newsService.symbolFeed(instrumentId, symbol, { page: 1, pageSize: 5, signal: controller.signal })
      .then((result) => { if (active) setFeed(result); })
      .catch(() => { if (active && !controller.signal.aborted) setError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [instrumentId, symbol]);

  function viewAll() {
    const params = new URLSearchParams({ news_instrument_id: instrumentId, news_symbol: symbol });
    navigate(`/news?${params.toString()}`);
  }

  return (
    <section className="panel-surface px-3 py-3 sm:px-4" aria-labelledby="stock-news-heading">
      <header className="mb-1 flex flex-wrap items-center justify-between gap-2 border-b border-terminal-border pb-2">
        <div className="min-w-0">
          <p className="text-2xs font-semibold uppercase tracking-[0.2em] text-terminal-accent">{symbol}</p>
          <h2 id="stock-news-heading" className="text-xs font-semibold tracking-wide text-terminal-text">
            Stock News
          </h2>
        </div>
        <Button size="sm" variant="secondary" onClick={viewAll}>
          View All
          <Icon name="chevronRight" size={12} />
        </Button>
      </header>
      {loading && !feed ? <p className="py-4 text-xs text-terminal-muted">Loading Yahoo Finance headlines…</p> : null}
      {error && !feed ? <p role="status" className="py-4 text-xs text-terminal-muted">Stock news is temporarily unavailable.</p> : null}
      {!loading && !error && feed?.items.length === 0 ? <p className="py-4 text-xs text-terminal-muted">No cached headlines for {symbol} yet.</p> : null}
      <div>
        {(feed?.items ?? []).slice(0, 5).map((article: NewsArticle) => (
          <article key={article.id} className="flex items-start justify-between gap-3 border-b border-terminal-borderSoft py-2.5 last:border-0">
            <div className="min-w-0">
              <a href={article.article_url} target="_blank" rel="noopener noreferrer" className="line-clamp-2 text-xs font-medium leading-5 text-terminal-text underline-offset-4 hover:text-white hover:underline">
                {article.title}
              </a>
              <p className="mt-1 text-2xs text-terminal-muted">
                {article.publisher || 'Yahoo Finance'} · {publishedLabel(article.published_at)}
              </p>
            </div>
            <a
              href={article.article_url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Open: ${article.title}`}
              className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded text-terminal-muted transition-colors hover:bg-white/[0.06] hover:text-terminal-accent"
            >
              <Icon name="external" size={13} />
            </a>
          </article>
        ))}
      </div>
    </section>
  );
}
