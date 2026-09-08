# Vendor Portal

A Frappe app that extends ERPNext's Buying module with vendor onboarding, purchase controls,
automatic performance rating, and reporting — without modifying ERPNext or Frappe core.

The problem it solves: purchasing decisions are made on a Supplier record that says nothing about
how that vendor has performed. This app records performance as it happens, surfaces it where
buyers work, and refuses orders to vendors the business has decided against.

---

## What it does

**Onboarding.** Vendors apply through a submittable Vendor Onboarding record. Validation covers
GST and PAN format, email, and a configurable minimum of supporting documents. A four-state
workflow moves an application from draft to approved or rejected, and approval creates the
ERPNext Supplier automatically.

**Purchase controls.** Orders to blacklisted suppliers are refused. So are orders to suppliers
rated below the minimum their category demands. Both rules run server-side in an overridden
Purchase Order controller.

**Automatic rating.** Submitting a purchase order scores the vendor on pricing against their own
history. Submitting a receipt scores them on delivery timeliness and completeness. Cancelling
either withdraws the score. A nightly job reconciles every supplier's overall rating against the
log those scores live in.

**Reporting.** Two script reports, a purchase order print format carrying the vendor's standing,
and an analytics dashboard.

**Self-service.** Vendors apply at `/vendor-register` without a Desk account and check their
application at `/vendor-status`. Neither route grants Guest any DocType permission — both go
through whitelisted endpoints that build the document server-side from an allowlist of fields.

---

## Setup

From a bench with Frappe and ERPNext v16 installed:

```bash
bench get-app vendor_portal https://github.com/rakshitsharma0402/vendor_portal
bench --site vendor.localhost install-app vendor_portal
bench --site vendor.localhost migrate
bench build --app vendor_portal
bench restart
```

The app declares `required_apps = ["erpnext"]` and will not install without it.

Installing runs three data migration patches and imports fixtures: five vendor categories, six
custom fields on Supplier, the onboarding workflow and its states, and two roles. Nothing else is
needed — the app is usable immediately after `migrate`.

### After installing

Open **Vendor Portal Settings** and set **Default Supplier Group**. Approval creates Suppliers
using it, and ERPNext requires one.

---

## DocTypes

| DocType | Purpose |
|---|---|
| **Vendor Category** | Classification driving payment terms and the minimum rating acceptable for purchasing. Named by category name. Five seeded. |
| **Vendor Onboarding** | A vendor's application. Submittable, named `VOB-.YYYY.-.#####`, governed by a workflow. |
| **Vendor Document** | Child table on the above: one supporting document per row, verified individually. |
| **Vendor Rating Log** | One scored observation about a supplier. Named `VRL-.YYYY.-.#####`. Scores are 1–5. Every rating in the system derives from these. |
| **Vendor Portal Settings** | Singleton. Rating weights, thresholds, and onboarding rules. Read by every controller, job and report rather than hardcoded anywhere. |

Six custom fields are added to ERPNext's **Supplier** via fixtures: `custom_vendor_category`,
`custom_vendor_rating`, `custom_total_rating_count`, `custom_onboarding_reference`,
`custom_is_blacklisted`, `custom_blacklist_reason`.

---

## API

All whitelisted, all in `vendor_portal/api.py`, reachable at
`/api/method/vendor_portal.api.<name>`.

| Method | Returns |
|---|---|
| `get_vendor_dashboard(supplier)` | Order, receipt, invoice and rating totals for one supplier, plus a per-type rating breakdown and the ten most recent ratings. |
| `submit_vendor_rating(supplier, rating_type, score, remarks, purchase_order, purchase_receipt)` | Creates a rating log and recalculates the supplier's weighted score. |
| `get_supplier_comparison(item_code, qty)` | Every supplier who has supplied an item, with pricing, volume, rating and delivery score, best-rated first. |
| `get_onboarding_status_summary()` | Counts per onboarding status and the ten most recent applications, filtered to what the caller may see. |
| `set_supplier_blacklist(supplier, blacklisted, reason)` | Blacklists or reinstates a supplier. Purchase Manager or Vendor Manager only. |
| `bulk_import_vendors(csv_content)` | Queues a CSV of vendors for import as draft applications. |
| `get_dashboard_data()` | The four datasets the analytics page draws. |

The onboarding decision endpoints live with their DocType:
`vendor_portal.vendor_portal.doctype.vendor_onboarding.vendor_onboarding.approve_onboarding` and
`.reject_onboarding`.

---

## Overrides: which mechanism, and why

This is the central design question the app answers, and it answers it twice, differently.

**`override_doctype_class` on Purchase Order.** The blacklist gate and the rating gate decide
whether a purchase order is *valid at all*. An order to a vendor the business has blacklisted is
not a real order, and that judgement belongs inside the document's own validation, participating
in the controller's method resolution. Every overridden method calls `super()` first, so ERPNext
has established supplier, currency and totals before anything here reads them — and a document
ERPNext itself rejects never reaches these checks.

**`doc_events` on Purchase Receipt.** A short or late delivery does not make a receipt invalid.
It is an observation about an event the document happens to record: additive, and removable
without changing what a Purchase Receipt is. That is what `doc_events` is for.

**The rule this codebase follows:** if the behaviour changes whether the document is acceptable,
override the class. If it reacts to the document having happened, hook the event.

**Trade-offs.** `override_doctype_class` is exclusive — only one app can claim a DocType, so two
apps both needing deep Purchase Order changes will conflict, and the loser silently doesn't
apply. It also couples you to ERPNext's method signatures across upgrades. `doc_events` composes
freely, several apps can hook the same event, and nothing breaks if ERPNext restructures the
controller internally — but a hook cannot call `super()`, cannot intervene between ERPNext's own
steps, and cannot be relied on to run in any particular order relative to other apps' hooks.

**On JavaScript, the same question has the opposite answer.** `frappe.ui.form.on` is additive:
registering a `refresh` handler for Purchase Invoice leaves ERPNext's own intact.
`frappe.listview_settings["Purchase Order"]` is an object, and assigning to it destroys whatever
was there — so the list override merges with `Object.assign` and returns undefined for states it
does not handle, letting ERPNext's indicator apply. That override is also registered through
`doctype_list_js` rather than `app_include_js`, because `app_include_js` loads *before* ERPNext's
per-doctype list script, which then assigns over it.

---

## Permissions

Two roles ship as fixtures:

**Vendor Manager** — full access to every portal DocType, including delete and cancel. May
approve, reject and blacklist.

**Purchase Team** — may create and submit applications and create rating logs. Read-only on
Vendor Category and Vendor Portal Settings. No cancel, no delete.

Both sit alongside ERPNext's own Purchase User or Purchase Manager, which continue to govern
Purchase Order, Receipt and Invoice — this app defines no permissions on ERPNext DocTypes.

Row-level rules narrow further:

- `permission_query_conditions` on Vendor Onboarding restricts non-managers to applications they
  own, applied to every list, report and `frappe.get_list` at once
- `has_permission` on Vendor Rating Log, with a matching check in the controller's `validate`,
  restricts editing to the rating's author

The controller check exists because the `has_permission` hook does not gate a save for a user who
already holds doctype-level write permission. That was found by a test, not by reading the docs.

---

## Scheduled jobs

| Schedule | Job | Does |
|---|---|---|
| Daily | `recalculate_all_vendor_ratings` | Reconciles every rated supplier against its log; alerts Vendor Managers when one crosses below the threshold. |
| Hourly | `rate_pending_deliveries` | Rates submitted receipts the submit hook never saw. |
| Weekly | `send_performance_digest` | Emails a summary: best and worst vendors, the period's orders, new applications, everyone below threshold. |
| `0 9 * * *` | `expire_stale_onboardings` | Reminds at 7 days, auto-rejects at 14. |

Every job is safe to run twice. Each either recomputes from source or checks whether its work is
already done — the scheduler retries, and a developer will run them by hand.

---

## Reports and print format

**Vendor Performance** — one row per supplier: order volume and value, receipts, per-type rating
averages, on-time percentage and short delivery count. Four optional filters, bar chart of the
best-rated ten.

**Purchase Analysis by Vendor Category** — spend, supplier counts, purchased quantity and average
rating per category, naming the worst-rated supplier in each. Pie chart of spend distribution.

**Purchase Order with Vendor Standing** — a print format carrying the vendor's category badge and
rating as stars, with a caution note when the supplier is rated below 3.

**Vendor Analytics** — a Desk page at `/app/vendor-analytics` with four charts.

---

## Testing

Tests run against a **dedicated site**, never a working one:

```bash
bench new-site test.localhost
bench --site test.localhost install-app erpnext
bench --site test.localhost install-app vendor_portal
bench --site test.localhost set-config allow_tests true
bench --site test.localhost run-tests --app vendor_portal
```

37 tests across onboarding validation, controller overrides, APIs and row-level permissions.

The dedicated site matters. ERPNext's test bootstrap creates its own company, fiscal years and
master data directly in whatever site the suite runs against — on a populated site it collides
with real records and leaves test data behind.

Tests build every record they need. Nothing depends on data a developer happened to leave.

---

## Optional features

All five extended features shipped:

- Vendor self-service registration and status lookup at `/vendor-register` and `/vendor-status`
- ERPNext Supplier Scorecard integration through a Custom Scorecard Variable
- Vendor analytics dashboard
- Bulk vendor import from CSV, processed through `frappe.enqueue`
- Supplier comparison matrix on the Purchase Order form

---

## Assumptions

Where a requirement was ambiguous, this is what was chosen.

- **Vendor categories are seeded through fixtures, not a patch.** Fixtures re-import on every
  migrate and restore from zero on a fresh site; a patch runs once and leaves a fresh site empty.
- **`vendor_rating` and `total_rating_count` are read-only on the Supplier form.** They are
  derived from the rating log by the daily job, so a hand-typed value would be silently
  overwritten rather than respected.
- **`require_gst_verification` means "a GST number is required".** Nothing in this app verifies a
  number against a GST authority, and reading the setting as a verification step would imply a
  capability that does not exist.
- **Supporting documents are optional at schema level.** The minimum count is enforced at submit
  rather than on save, so an application still being assembled remains saveable.
- **Onboarding age is measured from `creation`.** Nothing records when an application entered
  review; an application normally reaches Under Review on submission, so the two coincide except
  for a draft that sat unsubmitted.
- **Rating weights are renormalised across the types that have entries.** A vendor rated 5 on
  delivery and never scored on quality reads as 5, not dragged toward zero by three dimensions
  nobody measured. `total_rating_count` is what tells a reader how much to trust it.
- **Blacklisted suppliers are excluded from the comparison endpoint, not flagged.** The endpoint
  exists to choose who to order from, and orders to them are refused anyway.
- **Draft applications are counted separately from pending** in the pipeline summary. A draft
  waits on the applicant, not a reviewer, and folding it in would overstate a manager's queue.
- **"Active suppliers" in the category report means ordered from within the period**, not
  ERPNext's `disabled` flag. A supplier can be perfectly transactable and simply unused.
- **"Total items purchased" is summed quantity**, not a count of distinct item codes. Every
  neighbouring column measures volume or value.
- **Bulk import creates drafts and does not detect duplicates.** An imported row carries no
  attachments and would fail the document minimum at submit; and guessing at identity by email or
  GST would silently drop rows someone meant to import.
- **`All Supplier Groups` is deliberately unmapped in the category backfill patch.** It is
  ERPNext's root node rather than a classification, and every supplier defaults into it — mapping
  it would sweep every unclassified supplier into one arbitrary category.

---

## Limitations

What this app does not do, and what would break it.

- **Duplicate GST checking is partial.** A plain ERPNext v16 Supplier has no GST field — the
  India regional fields live in the separate India Compliance app — so uniqueness can only be
  enforced across applications this portal owns. A Supplier created directly in Desk has no GST
  number to collide with.
- **Bank details are not carried to the created Supplier.** ERPNext holds supplier banking in a
  separate Bank Account document, so mapping them means creating a second record.
- **Purchase order pricing comparison uses `grand_total` in document currency.** A supplier
  billed in two currencies would have unrelated amounts averaged together. `base_grand_total`
  would fix it; the dashboard and reports already use it.
- **The rating scale conversion exists twice.** `vendor_portal/utils.py` cannot be imported
  client-side, so the 0-1 to 1-5 arithmetic is repeated in JavaScript. Likewise the GST pattern,
  which exists in both the controller and the form script — a client check that asks the server
  whether a value is valid is not a client check.
- **The duplicate-GST check is a read-then-write with no lock.** Two simultaneous submissions of
  the same number would both pass. Closing it needs a unique index, which the field's optionality complicates.
- **The comment-mining patch skips negations rather than parsing them.** "Not late for once"
  matches "late", so any comment containing a negation is counted and skipped. A visible gap beats
  a plausible-looking score nobody can trace.
- **No outgoing email account is configured.** Onboarding notifications, low-rating alerts, the
  weekly digest and the stale-application reminders all log their failure and continue rather than
  raising. The features work; the mail does not leave.
- **Onboarding tests live in `vendor_portal/tests/` rather than beside their DocType.** Frappe
  v16 infers a test file's doctype from its folder and then generates test records for every
  doctype it links to, transitively — a walk that reaches `Payment Gateway`, which no longer
  exists, and fails before any test runs.
- **Field-level permissions on Supplier are not implemented.** Frappe offers nothing short of
  permission levels, and introducing those on a core ERPNext DocType is a large change for a small gain.
- **The scorecard variable depends on an import in `__init__.py`.** ERPNext resolves a variable's
  Python path with `__import__` on the first segment and `getattr` for the rest, and `getattr`
  does not trigger a submodule import — so `vendor_portal/__init__.py` imports the scorecard
  module for the sole purpose of making it reachable. Removing that line makes every scorecard
  period score zero, silently, because the function swallows its own failures.
- **The scorecard mean is unweighted.** A supplier's overall rating weights by type; the scorecard
  variable averages every rating in the period equally, because a period may contain one type and
  renormalising across that sample would produce a meaningless number. The two figures differ by
  design.

---

## Repository conventions

Branch per issue, cut from `main`, named `type/TICKET-description`. Merge commits rather than
squashes, so the granular history survives. Commits follow `type(scope): description` with the
reasoning in the body — the *why*, not the *what*.

`main` is always installable and migratable.