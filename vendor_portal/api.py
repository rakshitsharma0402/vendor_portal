# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Whitelisted endpoints for the vendor portal.

Everything the forms, dashboards and background jobs read about a vendor goes
through here rather than each caller assembling its own query, so a change to
what "total order value" means happens in one place.
"""

import frappe
from frappe import _

# How many rating entries the dashboard carries back. Enough to show a trend
# without turning a summary call into a full history fetch.
RECENT_RATINGS_LIMIT = 10


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

