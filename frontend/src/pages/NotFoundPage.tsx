import { Link } from 'react-router-dom';
import { Button } from '../components/common/Button';
import { PageHeader } from '../components/common/PageHeader';

export function NotFoundPage() {
  return (
    <div>
      <PageHeader title="Page not found" subtitle="This route does not exist in Tradely." />
      <div className="panel-surface flex flex-col items-start gap-3 p-6">
        <p className="text-sm text-terminal-muted">
          Check the address, or return to the dashboard to pick a section.
        </p>
        <Link to="/">
          <Button variant="primary">Back to dashboard</Button>
        </Link>
      </div>
    </div>
  );
}
