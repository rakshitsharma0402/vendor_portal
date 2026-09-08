# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Whitelisted endpoints for the vendor portal.

Everything the forms, dashboards and background jobs read about a vendor goes
through here rather than each caller assembling its own query, so a change to
what "total order value" means happens in one place.
"""

import frappe
import csv
import io
from frappe import _
from frappe.utils import add_months, cint, flt, today
from vendor_portal.utils import (
	RATING_TYPE_WEIGHTS,
	rating_field_to_scale,
	recalculate_vendor_rating,
)

# How many rating entries the dashboard carries back. Enough to show a trend
# without turning a summary call into a full history fetch.
RECENT_RATINGS_LIMIT = 10
MIN_SCORE = 1.0
MAX_SCORE = 5.0

from vendor_portal.vendor_portal.doctype.vendor_onboarding.vendor_onboarding import (
	DECISION_ROLES,
)

@frappe.whitelist()
def get_vendor_dashboard(supplier: str) -> dict:
	"""Summarise a vendor's ordering, receiving, invoicing and rating history.

	Each figure is counted against its own table rather than assembled from a
	single join. Joining orders, receipts and invoices for one supplier
	produces a row per combination — three orders and two receipts give six
	rows — and every total computed across them is multiplied by the others.
	Separate statements cost more round trips and return correct numbers.

	Args:
		supplier: Name of the Supplier to summarise.

	Returns:
		A dict of totals, a per-type rating breakdown, and the most recent
		rating entries. A vendor with no history returns zeroes and empty
		lists rather than nulls, so callers can render without guarding.

	Raises:
		frappe.ValidationError: If the supplier does not exist.
	"""
	try:
		if not frappe.db.exists("Supplier", supplier):
			frappe.throw(
				_("Supplier {0} not found.").format(frappe.bold(supplier)),
				title=_("Unknown Supplier"),
			)

		orders = _get_order_summary(supplier)
		receipts = _get_receipt_summary(supplier)
		invoices = _get_invoice_summary(supplier)
		ratings = _get_rating_summary(supplier)

		return {
			"supplier": supplier,
			**orders,
			**receipts,
			**invoices,
			**ratings,
		}

	except Exception:
		frappe.log_error(title="Vendor dashboard fetch failed")
		raise


def _get_order_summary(supplier: str) -> dict:
	"""Count submitted purchase orders and their total value.

	Draft orders are not commitments and cancelled ones did not happen, so
	only docstatus 1 is counted. Value is summed in company currency: a
	supplier billed in more than one currency would otherwise have unrelated
	amounts added together.

	Args:
		supplier: Name of the Supplier.

	Returns:
		total_pos, total_po_value and pending_receipts.
	"""
	result = frappe.db.sql(
		"""
		SELECT
			COUNT(*) AS total_pos,
			COALESCE(SUM(base_grand_total), 0) AS total_po_value,
			COALESCE(SUM(CASE WHEN per_received < 100 THEN 1 ELSE 0 END), 0) AS pending_receipts
		FROM `tabPurchase Order`
		WHERE supplier = %(supplier)s
			AND docstatus = 1
		""",
		{"supplier": supplier},
		as_dict=True,
	)

	row = result[0] if result else {}

	return {
		"total_pos": int(row.get("total_pos") or 0),
		"total_po_value": float(row.get("total_po_value") or 0),
		"pending_receipts": int(row.get("pending_receipts") or 0),
	}


def _get_receipt_summary(supplier: str) -> dict:
	"""Count submitted purchase receipts.

	Args:
		supplier: Name of the Supplier.

	Returns:
		total_receipts.
	"""
	total = frappe.db.count("Purchase Receipt", {"supplier": supplier, "docstatus": 1})

	return {"total_receipts": total}


def _get_invoice_summary(supplier: str) -> dict:
	"""Total what has been invoiced and what remains unpaid.

	Args:
		supplier: Name of the Supplier.

	Returns:
		total_invoiced and outstanding_amount, both in company currency.
	"""
	result = frappe.db.sql(
		"""
		SELECT
			COALESCE(SUM(base_grand_total), 0) AS total_invoiced,
			COALESCE(SUM(outstanding_amount), 0) AS outstanding_amount
		FROM `tabPurchase Invoice`
		WHERE supplier = %(supplier)s
			AND docstatus = 1
		""",
		{"supplier": supplier},
		as_dict=True,
	)

	row = result[0] if result else {}

	return {
		"total_invoiced": float(row.get("total_invoiced") or 0),
		"outstanding_amount": float(row.get("outstanding_amount") or 0),
	}


def _get_rating_summary(supplier: str) -> dict:
	"""Average the vendor's ratings overall and by type, and list recent ones.

	Reports what the rating log holds rather than the cached value on the
	Supplier record. The two can disagree between a rating being entered and
	the recalculation that follows it, and the log is the source of truth.

	Scores are already on the 1-5 scale here — no conversion, unlike the
	Supplier field, which stores a fraction.

	Args:
		supplier: Name of the Supplier.

	Returns:
		avg_rating, rating_breakdown by type, and recent_ratings.
	"""
	overall = frappe.db.sql(
		"""
		SELECT COALESCE(AVG(score), 0) AS avg_rating
		FROM `tabVendor Rating Log`
		WHERE supplier = %(supplier)s
		""",
		{"supplier": supplier},
		as_dict=True,
	)

	breakdown = frappe.db.sql(
		"""
		SELECT
			rating_type,
			AVG(score) AS average_score,
			COUNT(*) AS rating_count
		FROM `tabVendor Rating Log`
		WHERE supplier = %(supplier)s
		GROUP BY rating_type
		ORDER BY rating_type
		""",
		{"supplier": supplier},
		as_dict=True,
	)

	recent = frappe.get_all(
		"Vendor Rating Log",
		filters={"supplier": supplier},
		fields=["name", "rating_date", "rating_type", "score", "remarks"],
		order_by="rating_date desc, creation desc",
		limit=RECENT_RATINGS_LIMIT,
	)

	return {
		"avg_rating": float(overall[0].get("avg_rating") or 0) if overall else 0.0,
		"rating_breakdown": [
			{
				"rating_type": row.rating_type,
				"average_score": float(row.average_score or 0),
				"rating_count": int(row.rating_count or 0),
			}
			for row in breakdown
		],
		"recent_ratings": recent,
	}

@frappe.whitelist()
def submit_vendor_rating(
	supplier: str,
	rating_type: str,
	score: float,
	remarks: str | None = None,
	purchase_order: str | None = None,
	purchase_receipt: str | None = None,
) -> dict:
	"""Record a rating for a supplier and update its overall score.

	The recalculation runs inline rather than in a background job: a buyer who
	rates a vendor and then opens the supplier list expects the new number to
	be there, and the work is one grouped query against one supplier.

	Args:
		supplier: Name of the Supplier being rated.
		rating_type: One of Delivery, Quality, Pricing or Communication.
		score: The rating on the 1-5 scale.
		remarks: Optional note explaining the score.
		purchase_order: Optional order this rating arose from.
		purchase_receipt: Optional receipt this rating arose from.

	Returns:
		The created log's name, the recalculated rating on the 1-5 scale, and
		the number of ratings behind it.

	Raises:
		frappe.ValidationError: If the supplier is unknown, the rating type is
			not recognised, or the score falls outside 1-5.
	"""
	try:
		if not frappe.db.exists("Supplier", supplier):
			frappe.throw(
				_("Supplier {0} not found.").format(frappe.bold(supplier)),
				title=_("Unknown Supplier"),
			)

		if rating_type not in RATING_TYPE_WEIGHTS:
			frappe.throw(
				_("{0} is not a valid rating type.").format(frappe.bold(rating_type)),
				title=_("Invalid Rating Type"),
			)

		# Checked here as well as in the Vendor Rating Log controller so the
		# caller gets a clear refusal before anything is created, rather than
		# a validation error from a document they did not know existed.
		score = flt(score)

		if not MIN_SCORE <= score <= MAX_SCORE:
			frappe.throw(
				_("Score must be between 1 and 5."),
				title=_("Invalid Score"),
			)

		log = frappe.get_doc(
			{
				"doctype": "Vendor Rating Log",
				"supplier": supplier,
				"rating_type": rating_type,
				"score": score,
				"remarks": remarks,
				"purchase_order": purchase_order,
				"purchase_receipt": purchase_receipt,
			}
		)

		log.insert()

		recalculated = recalculate_vendor_rating(supplier)

		return {
			"rating_log": log.name,
			"rating": recalculated["rating"],
			"rating_count": recalculated["rating_count"],
		}

	except Exception:
		frappe.log_error(title="Vendor rating submission failed")
		raise


@frappe.whitelist()
def get_supplier_comparison(item_code: str, qty: float = 1) -> list[dict]:
	"""Compare the suppliers who have supplied an item.

	Args:
		item_code: The item to compare suppliers for.
		qty: Quantity being considered, used to project cost. Defaults to 1.

	Returns:
		One row per supplier who has supplied the item on a submitted order,
		ordered by rating descending then average rate ascending — best
		performer first, cheapest as the tiebreak. An item nobody has supplied
		returns an empty list.

	Raises:
		frappe.ValidationError: If the item does not exist.
	"""
	try:
		if not frappe.db.exists("Item", item_code):
			frappe.throw(
				_("Item {0} not found.").format(frappe.bold(item_code)),
				title=_("Unknown Item"),
			)

		qty = flt(qty) or 1

		rows = _get_item_purchase_history(item_code)

		if not rows:
			return []

		delivery_scores = _get_delivery_scores([row.supplier for row in rows])

		comparison = []

		for row in rows:
			last_rate = flt(row.last_rate)

			comparison.append(
				{
					"supplier": row.supplier,
					"supplier_name": row.supplier_name,
					"last_rate": last_rate,
					"avg_rate": flt(row.avg_rate),
					"total_supplied_qty": flt(row.total_supplied_qty),
					"estimated_cost": last_rate * qty,
					# Stored as a 0-1 fraction; callers compare against
					# thresholds expressed out of five.
					"vendor_rating": rating_field_to_scale(row.custom_vendor_rating),
					"delivery_score": delivery_scores.get(row.supplier),
				}
			)

		return comparison

	except Exception:
		frappe.log_error(title="Supplier comparison failed")
		raise


def _get_item_purchase_history(item_code: str) -> list[dict]:
	"""Summarise what each supplier has charged for an item.

	Joins order items to their parent orders — child to parent in one
	direction, so each order item contributes exactly one row. This is safe in
	a way the dashboard's four-way join was not: there is no second one-to-many
	relationship to multiply against.

	The average rate is weighted by quantity rather than taken across order
	lines. A plain mean would let a single one-unit sample at a high rate
	outweigh a thousand-unit order at the real price, and misrepresent the
	supplier permanently.

	Blacklisted suppliers are excluded: the point of this comparison is
	choosing who to order from, and orders to them are refused anyway.

	Args:
		item_code: The item to summarise.

	Returns:
		One row per supplier, ordered best-rated first, cheapest as tiebreak.
	"""
	return frappe.db.sql(
		"""
		SELECT
			po.supplier,
			po.supplier_name,
			s.custom_vendor_rating,
			SUM(poi.qty) AS total_supplied_qty,
			SUM(poi.amount) / NULLIF(SUM(poi.qty), 0) AS avg_rate,
			SUBSTRING_INDEX(
				GROUP_CONCAT(poi.rate ORDER BY po.transaction_date DESC, po.creation DESC),
				',', 1
			) AS last_rate
		FROM `tabPurchase Order Item` poi
		INNER JOIN `tabPurchase Order` po ON po.name = poi.parent
		INNER JOIN `tabSupplier` s ON s.name = po.supplier
		WHERE poi.item_code = %(item_code)s
			AND po.docstatus = 1
			AND COALESCE(s.custom_is_blacklisted, 0) = 0
		GROUP BY po.supplier, po.supplier_name, s.custom_vendor_rating
		ORDER BY s.custom_vendor_rating DESC, avg_rate ASC
		""",
		{"item_code": item_code},
		as_dict=True,
	)


def _get_delivery_scores(suppliers: list[str]) -> dict:
	"""Average each supplier's Delivery ratings.

	Fetched for every supplier in one grouped query rather than one call per
	row: ten suppliers in a comparison should not mean ten round trips.

	The score covers all of a supplier's delivery ratings, not only those for
	the item being compared. Narrowing it would mean joining ratings through
	receipts to receipt items, and most delivery ratings carry no receipt link
	at all — the result would be mostly empty and read as though those vendors
	had never delivered.

	Args:
		suppliers: Supplier names to score.

	Returns:
		Supplier name to mean Delivery score. Suppliers with no delivery
		ratings are absent, so callers see null rather than a misleading zero.
	"""
	if not suppliers:
		return {}

	rows = frappe.db.sql(
		"""
		SELECT supplier, AVG(score) AS delivery_score
		FROM `tabVendor Rating Log`
		WHERE rating_type = 'Delivery'
			AND supplier IN %(suppliers)s
		GROUP BY supplier
		""",
		{"suppliers": tuple(suppliers)},
		as_dict=True,
	)

	return {row.supplier: flt(row.delivery_score) for row in rows}

# How many applications the pipeline summary carries back. A widget shows a
# handful; anyone wanting the full list opens the list view.
RECENT_SUBMISSIONS_LIMIT = 10

# Every status an application can hold, so the summary reports a zero rather
# than omitting a bucket nobody currently occupies.
ONBOARDING_STATUSES = ("Draft", "Under Review", "Approved", "Rejected")


@frappe.whitelist()
def get_onboarding_status_summary() -> dict:
	"""Report the shape of the onboarding pipeline.

	Counted through the ORM rather than raw SQL, deliberately: this is the one
	endpoint in the portal whose answer depends on who is asking. Once
	row-level permissions restrict the purchase team to their own submissions,
	`frappe.get_all` applies those conditions and a hand-written query would
	quietly report everyone's. A vendor's performance is objective; a queue is
	not.

	Returns:
		A count per status, the total across them, and the most recent
		applications. A site with no applications returns zeroes and an empty
		list rather than nulls, so a widget can render without guarding.
	"""
	try:
		rows = frappe.get_list(
			"Vendor Onboarding",
			# Cancelled applications keep whatever status they held, so
			# without this a cancelled review sits in the pending count
			# forever.
			filters={"docstatus": ("!=", 2)},
			# Counted in Python rather than by a SQL aggregate: v16's query
			# engine rejects function calls in a string field list, and the
			# dict form gives no predictable alias to read back. An onboarding
			# pipeline is small enough that one column per application costs
			# nothing, and get_all still applies row-level permissions.
			pluck="onboarding_status",
		)

		counts = {status: 0 for status in ONBOARDING_STATUSES}

		for status in rows:
			if status in counts:
				counts[status] += 1

		recent = frappe.get_list(
			"Vendor Onboarding",
			filters={"docstatus": ("!=", 2)},
			fields=[
				"name",
				"supplier_name",
				"company_name",
				"vendor_category",
				"onboarding_status",
				"creation",
			],
			order_by="creation desc",
			limit=RECENT_SUBMISSIONS_LIMIT,
		)

		return {
			# Draft is counted apart from pending: an application still being
			# assembled is waiting on the applicant, not on a reviewer, and
			# folding it in would overstate what a vendor manager has to do.
			"total_draft": counts["Draft"],
			"total_pending": counts["Under Review"],
			"total_approved": counts["Approved"],
			"total_rejected": counts["Rejected"],
			"total_applications": sum(counts.values()),
			"recent_submissions": recent,
		}

	except Exception:
		frappe.log_error(title="Onboarding summary fetch failed")
		raise


@frappe.whitelist()
def set_supplier_blacklist(
	supplier: str, blacklisted: bool | int, reason: str | None = None) -> dict:
	"""Blacklist a supplier, or lift an existing blacklist.

	An endpoint rather than a field write from the client, because refusing to
	draw a button is not access control: anyone holding write permission on
	Supplier could otherwise set the flag directly. The role is checked here,
	where it cannot be walked around.

	Args:
		supplier: Name of the Supplier.
		blacklisted: Truthy to blacklist, falsy to lift it.
		reason: Why the vendor is being blacklisted. Required when
			blacklisting; ignored when lifting.

	Returns:
		The supplier's name and its new blacklist state.

	Raises:
		frappe.PermissionError: If the caller holds no deciding role.
		frappe.ValidationError: If the supplier is unknown, or a blacklist is
			requested without a reason.
	"""
	try:
		if not set(DECISION_ROLES) & set(frappe.get_roles()):
			frappe.throw(
				_("Only a Purchase Manager can blacklist a supplier."),
				frappe.PermissionError,
				title=_("Not Permitted"),
			)

		if not frappe.db.exists("Supplier", supplier):
			frappe.throw(
				_("Supplier {0} not found.").format(frappe.bold(supplier)),
				title=_("Unknown Supplier"),
			)

		blacklisted = cint(blacklisted)

		# A blacklist a buyer cannot interpret is one they will escalate.
		# Lifting one needs no justification: the vendor is simply orderable
		# again.
		if blacklisted and not (reason or "").strip():
			frappe.throw(
				_("A reason is required to blacklist a supplier."),
				title=_("Reason Missing"),
			)

		frappe.db.set_value(
			"Supplier",
			supplier,
			{
				"custom_is_blacklisted": blacklisted,
				"custom_blacklist_reason": reason.strip() if blacklisted and reason else None,
			},
		)

		return {"supplier": supplier, "blacklisted": blacklisted}

	except Exception:
		frappe.log_error(title="Supplier blacklist update failed")
		raise


# Fields a row must carry to become an application worth reviewing. Anything
# beyond these is optional and passed through if the header names it.
BULK_IMPORT_REQUIRED_FIELDS = (
	"supplier_name",
	"company_name",
	"email",
	"phone",
	"vendor_category",
)

# Rows beyond this are refused rather than queued. A file this large is more
# likely a mistake — a full supplier export pasted in by accident — than an
# intended import, and finding out after the job has run is expensive.
BULK_IMPORT_MAX_ROWS = 1000


@frappe.whitelist()
def bulk_import_vendors(csv_content: str) -> dict:
	"""Queue a CSV of vendors for import as draft applications.

	Returns as soon as the file is understood rather than when the import
	finishes: a thousand rows would otherwise hold the request open long
	enough to time out. What the caller learns immediately is whether the file
	is usable; what happened to each row arrives by email.

	Args:
		csv_content: The file's contents, header row first.

	Returns:
		How many rows were queued.

	Raises:
		frappe.PermissionError: If the caller holds no deciding role.
		frappe.ValidationError: If the file is empty, missing required
			headers, or larger than the row limit.
	"""
	try:
		if not set(DECISION_ROLES) & set(frappe.get_roles()):
			frappe.throw(
				_("Only a Purchase Manager can import vendors."),
				frappe.PermissionError,
				title=_("Not Permitted"),
			)

		rows = _parse_vendor_csv(csv_content)

		frappe.enqueue(
			"vendor_portal.api.import_vendor_rows",
			queue="long",
			rows=rows,
			requested_by=frappe.session.user,
		)

		return {"queued": len(rows)}

	except Exception:
		frappe.log_error(
			title="Bulk vendor import failed",
			message=frappe.get_traceback(),
		)
		raise


def _parse_vendor_csv(csv_content: str) -> list[dict]:
	"""Read the CSV and confirm it can be imported at all.

	Structural problems are caught here, in the request, so the caller is told
	at once. Row-level problems are left to the worker: a single malformed GST
	should not stop the other nine hundred rows.

	Args:
		csv_content: The file's contents, header row first.

	Returns:
		One dict per row, carrying its line number for reporting.

	Raises:
		frappe.ValidationError: If the file is empty, missing required
			headers, or too large.
	"""
	if not (csv_content or "").strip():
		frappe.throw(_("The file is empty."), title=_("Nothing to Import"))

	reader = csv.DictReader(io.StringIO(csv_content))

	headers = {(field or "").strip() for field in (reader.fieldnames or [])}
	missing = [field for field in BULK_IMPORT_REQUIRED_FIELDS if field not in headers]

	if missing:
		frappe.throw(
			_("The file is missing these columns: {0}").format(", ".join(missing)),
			title=_("Missing Columns"),
		)

	rows = []

	for line_number, row in enumerate(reader, start=2):
		# Blank lines are skipped rather than reported: a trailing newline is
		# not a mistake anyone needs telling about.
		if not any((value or "").strip() for value in row.values()):
			continue

		cleaned = {
			key.strip(): (value or "").strip()
			for key, value in row.items()
			if key and (value or "").strip()
		}

		cleaned["_line"] = line_number
		rows.append(cleaned)

	if not rows:
		frappe.throw(_("The file has a header but no rows."), title=_("Nothing to Import"))

	if len(rows) > BULK_IMPORT_MAX_ROWS:
		frappe.throw(
			_("The file has {0} rows; at most {1} can be imported at once.").format(
				len(rows), BULK_IMPORT_MAX_ROWS
			),
			title=_("Too Many Rows"),
		)

	return rows


def import_vendor_rows(rows: list[dict], requested_by: str):
	"""Create a draft application for each row, reporting what failed.

	Applications are left unsubmitted. Submitting runs the duplicate-GST check
	and the minimum-document rule, which an imported row will usually fail
	because it carries no attachments — a reviewer should see the batch,
	complete it, and submit deliberately.

	Committed per row so a job killed at row four hundred leaves three hundred
	and ninety-nine applications rather than none.

	Args:
		rows: Parsed rows, each carrying its line number as `_line`.
		requested_by: Who asked for the import, and who hears how it went.
	"""
	created = []
	failed = []

	for row in rows:
		line = row.pop("_line", None)

		try:
			doc = frappe.get_doc({"doctype": "Vendor Onboarding", **row})
			doc.insert(ignore_permissions=True)

			frappe.db.commit()

			created.append(doc.name)

		except Exception as exception:
			# Rolled back to the last commit so a half-written row does not
			# poison the rows that follow it.
			frappe.db.rollback()

			failed.append((line, str(exception)))

	_report_import(created, failed, requested_by)


def _report_import(created: list[str], failed: list[tuple], requested_by: str):
	"""Tell the requester what the import did.

	The caller disconnected the moment the job was queued, so the outcome has
	to reach them some other way. Logged as well as emailed: mail can be
	unconfigured, and a record of what a batch import created is worth keeping
	regardless.

	Args:
		created: Names of the applications created.
		failed: Line number and reason for each row that did not import.
		requested_by: Who to tell.
	"""
	lines = [f"Created {len(created)} draft application{'' if len(created) == 1 else 's'}."]

	if failed:
		lines.append(f"\n{len(failed)} row{'' if len(failed) == 1 else 's'} failed:")
		lines.extend(f"  Line {line}: {reason}" for line, reason in failed)

	message = "\n".join(lines)

	frappe.log_error(title="Bulk vendor import completed", message=message)

	try:
		frappe.sendmail(
			recipients=[requested_by],
			subject=_("Vendor import finished: {0} created, {1} failed").format(
				len(created), len(failed)
			),
			message=f"<pre>{frappe.utils.escape_html(message)}</pre>",
		)
	except Exception:
		frappe.log_error(
			title="Bulk vendor import notification failed",
			message=frappe.get_traceback(),
		)


# Rating bands for the distribution chart, as (label, lower, upper). The top
# band is closed at both ends so a supplier rated exactly 5 has somewhere to
# land rather than falling out of the histogram.
RATING_BANDS = (
	("1 – 2", 1.0, 2.0),
	("2 – 3", 2.0, 3.0),
	("3 – 4", 3.0, 4.0),
	("4 – 5", 4.0, 5.0),
)

DELIVERY_TREND_MONTHS = 12


@frappe.whitelist()
def get_dashboard_data() -> dict:
	"""Return every dataset the analytics page draws.

	One call rather than four. A dashboard asks a single question — how are
	our vendors doing — and answering it in four requests means the page
	renders in stages and pays the round trip four times.

	Returns:
		Four datasets, each a list of labels and values ready to plot. Empty
		lists where there is nothing to show, so the page can say so rather
		than drawing an empty chart.
	"""
	try:
		return {
			"rating_distribution": _get_rating_distribution(),
			"onboarding_pipeline": _get_onboarding_pipeline(),
			"category_spend": _get_category_spend(),
			"delivery_trend": _get_delivery_trend(),
		}

	except Exception:
		frappe.log_error(
			title="Dashboard data fetch failed",
			message=frappe.get_traceback(),
		)
		raise


def _get_rating_distribution() -> dict:
	"""Count rated suppliers falling in each rating band.

	Unrated suppliers are excluded rather than counted in the lowest band: a
	vendor nobody has scored is not a poorly performing one, and putting them
	in the 1-2 bucket would make a new site look like a disaster.

	Returns:
		Band labels and the number of suppliers in each.
	"""
	suppliers = frappe.db.sql_list(
		"""
		SELECT custom_vendor_rating
		FROM `tabSupplier`
		WHERE COALESCE(disabled, 0) = 0
			AND COALESCE(custom_total_rating_count, 0) > 0
		"""
	)

	if not suppliers:
		return {"labels": [], "values": []}

	counts = [0] * len(RATING_BANDS)

	for stored in suppliers:
		rating = rating_field_to_scale(stored)

		for index, (_label, lower, upper) in enumerate(RATING_BANDS):
			# The top band takes its upper bound inclusively so a supplier at
			# exactly five is counted rather than dropped.
			is_top = index == len(RATING_BANDS) - 1

			if lower <= rating < upper or (is_top and rating == upper):
				counts[index] += 1
				break

	return {
		"labels": [label for label, _lower, _upper in RATING_BANDS],
		"values": counts,
	}


def _get_onboarding_pipeline() -> dict:
	"""Count applications by status.

	Returns:
		Status labels and counts, every status present even at zero.
	"""
	rows = frappe.db.sql(
		"""
		SELECT onboarding_status, COUNT(*) AS status_count
		FROM `tabVendor Onboarding`
		WHERE docstatus != 2
		GROUP BY onboarding_status
		""",
		as_dict=True,
	)

	counts = {status: 0 for status in ONBOARDING_STATUSES}

	for row in rows:
		if row.onboarding_status in counts:
			counts[row.onboarding_status] = int(row.status_count or 0)

	if not sum(counts.values()):
		return {"labels": [], "values": []}

	return {"labels": list(counts.keys()), "values": list(counts.values())}


def _get_category_spend() -> dict:
	"""Total submitted purchase order value by vendor category.

	Aggregated here rather than by calling the category report: that report
	returns columns and rows shaped for a grid, and reshaping them in
	JavaScript is worse than a small query. Known duplication, deliberate.

	Returns:
		Category labels and their spend, highest first.
	"""
	rows = frappe.db.sql(
		"""
		SELECT s.custom_vendor_category AS category,
			COALESCE(SUM(po.base_grand_total), 0) AS spend
		FROM `tabPurchase Order` po
		INNER JOIN `tabSupplier` s ON s.name = po.supplier
		WHERE po.docstatus = 1
			AND COALESCE(s.custom_vendor_category, '') != ''
		GROUP BY s.custom_vendor_category
		HAVING spend > 0
		ORDER BY spend DESC
		""",
		as_dict=True,
	)

	return {
		"labels": [row.category for row in rows],
		"values": [flt(row.spend) for row in rows],
	}


def _get_delivery_trend() -> dict:
	"""Average delivery score by month over the last year.

	Monthly rather than weekly: on a site with a handful of receipts a weekly
	line is mostly noise, and twelve points is enough to see a direction.

	Returns:
		Month labels and the mean delivery score in each, oldest first.
	"""
	rows = frappe.db.sql(
		"""
		SELECT DATE_FORMAT(rating_date, '%%b %%Y') AS month_label,
			DATE_FORMAT(rating_date, '%%Y-%%m') AS month_key,
			AVG(score) AS average_score
		FROM `tabVendor Rating Log`
		WHERE rating_type = 'Delivery'
			AND rating_date >= %(from_date)s
		GROUP BY month_key, month_label
		ORDER BY month_key ASC
		""",
		{"from_date": add_months(today(), -DELIVERY_TREND_MONTHS)},
		as_dict=True,
	)

	return {
		"labels": [row.month_label for row in rows],
		"values": [round(flt(row.average_score), 2) for row in rows],
	}