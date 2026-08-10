# `docs/todo/` Migration Freeze

Status: **MIGRATION_FROZEN**

GitHub Issues are being introduced as the operational work inventory for Synth v2. The existing `docs/todo/` tree remains readable during controlled migration, but it must not expand into a second board.

## Effective rules

- Do not create new TODO lane files.
- Do not extend the planned TODO subfolder information architecture.
- New executable work belongs in GitHub Issues.
- Existing TODO files may be edited only to:
  - correct unsafe or materially false information;
  - point to the owning GitHub Issue;
  - move permanent content to canonical documentation;
  - archive or remove superseded content in a reviewed migration change.
- `docs/todo/README.md` remains a legacy migration inventory until every listed item has an explicit disposition. It no longer defines new work intake.
- Do not bulk-create Issues from file names or headings.

## Allowed dispositions

Each existing TODO file must receive exactly one reviewed disposition:

1. `issue` — active, bounded executable work with a concrete next action;
2. `canonical` — permanent architecture, strategy, research, operations, or status content;
3. `archive` — obsolete or superseded material with historical value;
4. `remove` — proven duplicate with no unique evidence or contract.

## Canonical workflow

See:

```text
docs/development/github_issues_workflow.md
```

## Safety boundary

This freeze changes documentation governance only.

- Runtime changes: none
- Database changes: none
- Broker writes: 0
- Order submissions: 0
- Service/timer changes: none
