# Project Instructions

Apply these instructions to the code you change. Review history explains the
conventions below; use the current task, API contract, and implementation when a
historical comment has been superseded.

## Infrastructure

- Consider the repo is mirrored to a self hosted GitLab with version 14.8.2
- Develop and merge on GitHub. The mirror updates `main`, `develop`, and tags;
  deployment runs from the protected GitLab `main`. Follow `docs/deploy-aws.md`.
- Check CI syntax against GitLab **14.8.2**, not just the latest documentation.
  `id_tokens` is unsupported here; the deployment uses `CI_JOB_JWT_V2`, with the
  GitLab URL as its OIDC audience. Keep token configuration and IAM trust aligned.
- For Terraform or deployment script changes, run the checks in
  `.github/workflows/terraform.yml`: formatting, initialization with
  `-backend=false -input=false -lockfile=readonly`, validation, mocked Terraform
  tests, and the relevant Bash syntax checks and `scripts/tests/` suites.
- Preserve the provider lock file and existing state identity. Keep validation
  separate from applying infrastructure. Report local checks and live deployment
  results separately; passing mocks or adding retries does not prove that a
  remote GitLab, mirror, or AWS failure is fixed.

## Task scope and integration

- Read the task's latest acceptance criteria, relevant discussion, and neighboring
  implementation before coding. Match the specified HTTP method, route, response,
  status codes, and state transitions. Document unresolved requirements rather
  than inventing product rules or expanding the task into related features.
- Use `tidXXX/name-of-branch` when creating a contribution branch; use the actual
  task ID. Feature PRs normally target `develop`; check the intended base.
- Integrate the current target branch before final validation when preparing a
  PR. Resolve semantic conflicts too: unchanged Git merges can still break model
  fields, route prefixes, tests, package exports, or the migration graph.
- After integration, rerun affected tests against the combined code. Check
  current authentication helpers and payloads rather than copying old endpoints.
- Keep the diff focused on the task and preserve unrelated work already present.

## Architecture and reuse

- Follow the existing flow: routes and DTOs in `app/presentation`, business
  services and entities in `app/domain`, and SQLAlchemy persistence in
  `app/infrastructure/repository`. Use mappers for input and assemblers for output.
- Match neighboring names: services such as `TagsService` with descriptive
  methods such as `get_tags`, and repository modules such as `tag.py`. Avoid a
  new naming convention or generic `execute` method for an existing service family.
- Reuse existing repository lookups and model-to-entity conversion methods.
  Search for equivalent logic before adding another `get_event` or `_to_entity`.
  Extend a shared conversion when needed so related endpoints stay consistent.
- Preserve `__init__.py` exports and router registration when adding or moving
  modules; package-level imports are part of the existing integration.
- Derive redundant values instead of storing another source of truth. For tags,
  `tag_type` comes from `tag_parent_id`; it may still be required in response DTOs.
- Avoid permanent caches for data that can change. If caching is warranted,
  define a lifetime or invalidation mechanism and test updates becoming visible.

## Validation, authentication, and errors

- Bound external inputs in DTOs: string lengths and formats, collection sizes,
  pagination limits, and token formats. Reuse existing constants and validators;
  enforce limits before constructing large database queries.
- Reuse `get_current_user` for authenticated routes and enforce ownership and
  visibility rules. Preserve active-record filters such as `deleted_at IS NULL`
  in write lookups too; authentication alone does not replace those filters.
- Give each validation rule a clear owner. Avoid repeated queries for the same
  check or guards for states the caller cannot produce. Retain database
  constraints and handle relevant integrity failures instead of inventing races
  that require unimplemented features.
- Use the existing domain exceptions and HTTP error mappings for expected
  failures. Do not introduce an unhandled `ValueError` that turns a client error
  into a 500. Document relevant errors in OpenAPI and assert exact status codes.
- For status and time restrictions, check every affected participant/event state
  and the time boundary, not only the happy path or an explicit `FINISHED` flag.
- When changing configuration parsing or CORS, cover whitespace/empty entries,
  allowed and disallowed origins, and preflight behavior as applicable.

## Persistence, migrations, and side effects

- Use the existing SQLAlchemy typed declarative style: `Mapped[...]`,
  `mapped_column`, and typed relationships. Keep DTO limits and database column
  lengths consistent, and use constraints for persistence invariants.
- Account for `expire_on_commit=True`: accessing relationships after `commit()`
  can discard ordering/eager loading and cause new queries. Build response
  entities from the ordered, loaded result before committing, or explicitly
  requery with the required ordering/loading afterward.
- Include a reviewed Alembic migration for persisted schema changes. Tests using
  `Base.metadata.create_all()` do not prove that deployment creates the schema.
- Check `alembic heads` after integrating the target branch and leave a single
  head. Reconcile duplicate merge revisions. Preserve revisions already applied
  in shared environments; join their history with a merge revision rather than
  deleting or rewriting them.
- Validate `alembic upgrade head` on a fresh PostgreSQL database and one already
  migrated to the target branch when changing migrations. Check schema/model
  agreement and preserve existing data through the upgrade.
- Make transaction boundaries explicit. Notification/push failures must not
  leave the business operation partially committed or prevent an otherwise
  successful action. Preserve the dispatcher's failure isolation; test failures,
  recipients, and triggers, including no notification for an unchanged value.

## Tests and development data

- Use the Dev Container/PostgreSQL setup in `README.md` for integration checks.
  SQLite tests are useful, but do not substitute for PostgreSQL migration checks.
- Add regression tests that demonstrate the changed behavior: success, relevant
  errors, ownership/isolation, state transitions, and idempotency when applicable.
  Assert exact response values with controlled configuration.
- Choose fixtures that can reveal bugs: for ordering tests, UUID order must differ
  from display-name order; for time rules, cover the boundary and elapsed time
  without an explicit status change.
- Test the real `app.seed` when behavior relies on demo data, including macro and
  micro tags. Keep seeds deterministic and idempotent, preserve user-created data
  and existing read state except for explicitly documented demo resets.
- For Python changes, run `ruff check .`, `ruff format --check .`, and
  `pytest --cov=app --cov-report=term-missing --cov-fail-under=90`, matching CI.
  For documentation-only changes, verify referenced paths and commands instead
  of running unrelated application tests. State any checks you could not run.
