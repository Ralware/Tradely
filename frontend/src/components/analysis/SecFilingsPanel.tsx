import { useState } from 'react';
import type { FormEvent } from 'react';
import { newsService } from '../../services/newsService';
import type { SecFilingsResponse } from '../../types/api';
import { Button } from '../common/Button';
import { Card } from '../common/Card';
import { Field, Input } from '../common/Field';
import { EmptyState, ErrorState, LoadingPanel, Notice } from '../common/States';
import { NewsList } from '../tables/NewsList';

export function SecFilingsPanel({ defaultCik }: { defaultCik?: string }) {
  const [cik, setCik] = useState(defaultCik ?? '');
  const [result, setResult] = useState<SecFilingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = cik.trim();
    if (!value) {
      setError('Enter a CIK.');
      return;
    }
    setError(null);
    setLoading(true);
    try {
      setResult(await newsService.getSecFilings(value));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'SEC EDGAR request failed');
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card
      title="SEC EDGAR filings"
      subtitle="Official US filings by CIK. Set SEC_USER_AGENT in .env to a real identifying contact first."
    >
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <Field label="Issuer CIK" className="min-w-[180px]">
          <Input
            value={cik}
            onChange={(event) => setCik(event.target.value)}
            placeholder="0000320193"
            inputMode="numeric"
          />
        </Field>
        <Button type="submit" loading={loading}>
          Load filings
        </Button>
      </form>

      <div className="mt-3">
        {error ? (
          <ErrorState message={error} />
        ) : loading ? (
          <LoadingPanel label="Fetching filings…" rows={3} />
        ) : result ? (
          result.items.length > 0 ? (
            <NewsList items={result.items} />
          ) : (
            <EmptyState title="No filings returned" description={`CIK ${result.cik} returned no recent filing records.`} icon="search" />
          )
        ) : (
          <Notice>
            Automatic issuer-to-CIK mapping is not implemented. Look up the CIK on sec.gov, then load
            the filing feed here.
          </Notice>
        )}
      </div>
    </Card>
  );
}
