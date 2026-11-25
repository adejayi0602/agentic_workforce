import { ApiStatus } from "@/components/api-status";

export default function OverviewPage() {
  return (
    <>
      <h1>Overview</h1>
      <p className="lede">
        Sprint 0 skeleton. Project intake, requirements, manifests and approvals arrive in the
        sprints shown in the navigation.
      </p>
      <section className="card" aria-labelledby="platform-status">
        <h2 id="platform-status">Platform status</h2>
        <ApiStatus />
      </section>
    </>
  );
}
