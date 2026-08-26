# Land acquisition portal registry

The registry is deliberately fail-closed. Named property portals are not read by the
generic HTML scanner and cannot be written by browser automation. Discovery is enabled
only for a documented licensed API/feed; publishing and withdrawal require a licensed
API adapter with an immutable receipt and read-back proof.

Every live adapter activation requires, outside this repository:

1. written commercial/API authority from the platform;
2. a Data Protection Impact Assessment and approved contact-basis policy;
3. adapter credentials in managed secrets, never in this JSON file;
4. staging contract tests for publish, read-back, idempotency and withdrawal;
5. explicit registry change reviewed by Legal and Operations.

The default registry keeps every external channel disabled. `imperial_plot_finder` is
also disabled until its canonical CMS contract and rollback/read-back endpoint are
registered.
