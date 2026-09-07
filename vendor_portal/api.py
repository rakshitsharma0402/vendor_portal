# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Whitelisted endpoints for the vendor portal.

Everything the forms, dashboards and background jobs read about a vendor goes
through here rather than each caller assembling its own query, so a change to
what "total order value" means happens in one place.
"""

import frappe
from frappe import _
from frappe.utils import flt
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
		rows = frappe.get_all(
			"Vendor Onboarding",
			# Cancelled applications keep whatever status they held, so
			# without this a cancelled review sits in the pending count
			# forever.
			filters={"docstatus": ("!=", 2)},
			fields=["onboarding_status", "count(name) as status_count"],
			group_by="onboarding_status",
		)

		counts = {status: 0 for status in ONBOARDING_STATUSES}

		for row in rows:
			if row.onboarding_status in counts:
				counts[row.onboarding_status] = int(row.status_count or 0)

		recent = frappe.get_all(
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