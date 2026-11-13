import { Link } from 'react-router-dom';
import type { CryptoMarket } from '../../types/api';
import { cn, formatCompact, formatNumber, toneForNumber } from '../../utils/format';
import { analysisPath } from '../../utils/navigation';
import { EmptyState } from '../common/States';

export function CryptoMarketsTable({ markets }: { markets: CryptoMarket[] }) {
  if (markets.length === 0) {
    return (
      <EmptyState
        title="No crypto market metadata"
        description="CoinGecko returned no rows. Configure COINGECKO_API_KEY to enable aggregate market data, or use the Crypto Analysis page with Binance Spot candles."
        icon="crypto"
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-terminal-border text-left text-[11px] uppercase tracking-[0.06em] text-terminal-muted">
            <th className="py-2 pr-3 font-medium">#</th>
            <th className="py-2 pr-3 font-medium">Asset</th>
            <th className="py-2 pr-3 text-right font-medium">Price</th>
            <th className="py-2 pr-3 text-right font-medium">24h</th>
            <th className="py-2 pr-3 text-right font-medium">Market cap</th>
            <th className="py-2 pr-3 text-right font-medium">Volume 24h</th>
            <th className="py-2 font-medium">Analysis</th>
          </tr>
        </thead>
        <tbody>
          {markets.map((market) => {
            const changeTone = toneForNumber(market.price_change_percentage_24h);
            const binanceSymbol = `${market.symbol.toUpperCase()}USDT`;
            return (
              <tr key={market.id} className="border-b border-terminal-borderSoft last:border-0">
                <td className="num py-2 pr-3 text-terminal-muted">{market.market_cap_rank ?? '—'}</td>
                <td className="py-2 pr-3">
                  <div className="flex items-center gap-2">
                    {market.image ? (
                      <img
                        src={market.image}
                        alt=""
                        width={16}
                        height={16}
                        loading="lazy"
                        className="h-4 w-4 rounded-full"
                      />
                    ) : null}
                    <div className="min-w-0">
                      <p className="font-medium text-terminal-text">{market.symbol.toUpperCase()}</p>
                      <p className="truncate text-[10px] text-terminal-muted">{market.name}</p>
                    </div>
                  </div>
                </td>
                <td className="num py-2 pr-3 text-right text-terminal-text">
                  {market.current_price === null ? '—' : formatNumber(market.current_price, 4)}
                </td>
                <td
                  className={cn(
                    'num py-2 pr-3 text-right font-medium',
                    changeTone === 'positive'
                      ? 'text-terminal-green'
                      : changeTone === 'negative'
                        ? 'text-terminal-red'
                        : 'text-terminal-muted',
                  )}
                >
                  {market.price_change_percentage_24h === null
                    ? '—'
                    : `${formatNumber(market.price_change_percentage_24h, 2)}%`}
                </td>
                <td className="num py-2 pr-3 text-right text-terminal-muted">
                  {formatCompact(market.market_cap)}
                </td>
                <td className="num py-2 pr-3 text-right text-terminal-muted">
                  {formatCompact(market.total_volume)}
                </td>
                <td className="py-2">
                  <Link
                    to={analysisPath(binanceSymbol, 'crypto', 'BINANCE')}
                    className="text-terminal-accent hover:underline"
                  >
                    {binanceSymbol}
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
