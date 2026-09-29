import { Link } from "react-router-dom";

import { AsyncState } from "../components/common/AsyncState";

export function NotFoundPage() {
  return <AsyncState title="Page not found" description="The requested workspace does not exist." action={<Link className="button-link" to="/incidents">Open incidents</Link>} />;
}
