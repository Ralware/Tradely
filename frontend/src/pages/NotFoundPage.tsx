import { Link } from "react-router-dom";
import { Button } from "../components/common/Button";
import { PageHeader } from "../components/common/PageHeader";

export function NotFoundPage() {
  return (
    <div className="app-page">
      <PageHeader title="Page Not Found" subtitle="This route does not exist" />
      <div className="panel-surface flex flex-col items-start gap-3 p-4">
        <p className="text-xs text-terminal-muted">
          Check the address or return to the dashboard.
        </p>
        <Link to="/">
          <Button variant="primary">Back to Dashboard</Button>
        </Link>
      </div>
    </div>
  );
}
