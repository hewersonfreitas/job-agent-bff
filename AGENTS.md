# Working agreement

Complete authorized work end to end: inspect contracts, implement, test, build Docker,
review security, commit, push, open a PR and inspect CI. Never merge automatically.
Preserve existing changes. Work on a feature branch; fetch main before starting.
Never reset --hard, clean -fd, remove existing volumes or overwrite operator secrets.
Use Conventional Commits and review the staged diff for sensitive files before push.
If a remote is empty, a minimal bootstrap commit may establish main for the first PR.

Use Context7 resolve-library-id then query-docs for current library/CLI documentation.
Do not introduce ATS business logic or a generic proxy. contracts/ pins backend v0.8;
check real upstream schemas before changing operations. Single operator only.
Credentials are operator-provisioned runtime files, never browser assets or Git data.
Keep mTLS verification, real DNS/SNI/Host, opaque hashed sessions, CSRF and no-store.
Never log bodies, credentials, cookies, document contents or raw upstream exceptions.

Run Ruff, pytest, contract and sensitive-file checks, Docker build and synthetic mTLS
integration before delivery. Report actual outcomes and environmental blockers.
Only disposable test credentials/data may be generated automatically. Docker tests
must use isolated projects and remove only their own containers/networks.
Ask for intervention only for real blockers or destructive actions outside authorization.
