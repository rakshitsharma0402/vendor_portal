# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Bridge from this app's rating log into ERPNext's Supplier Scorecard.

ERPNext scores suppliers through Scorecard Criteria that reference named
Variables. A Variable of type Custom names a Python path returning a number
for a supplier over a period — that is the seam this uses.

The alternative, writing Scorecard Periods directly, means reimplementing
ERPNext's evaluation cycle and having it overwritten on the next refresh.

Nothing here writes back. The rating log stays authoritative; the Scorecard
reads from it. Two-way sync between two scoring systems is how they come to
disagree permanently.
"""

import frappe
from frappe.utils import flt


def get_portal_rating(scorecard) -> float:
	"""Return the supplier's mean portal rating over the scorecard's period.

	Scoped to the period rather than the supplier's lifetime: the Scorecard
	measures periods, and a lifetime average would make every period identical
	and the trend it draws meaningless.

	The mean here is unweighted, unlike the supplier's overall rating: the
	Scorecard evaluates a period, and applying the portal's type weights to a
	window that may contain only one type would renormalise across a sample
	too small to mean anything. The two numbers legitimately differ.

	Never raises. A scorecard refresh evaluates every criteria for every
	supplier in one pass, so an exception here aborts the whole run — a wrong
	zero in one cell is better than no scorecard at all.

	Args:
		scorecard: The Supplier Scorecard Period being evaluated, carrying
			`supplier`, `start_date` and `end_date`.

	Returns:
		The mean rating on the 1-5 scale, or 0 when the supplier holds no
		ratings in the period.
	"""
	try:
		average = frappe.db.sql(
			"""
			SELECT AVG(score)
			FROM `tabVendor Rating Log`
			WHERE supplier = %(supplier)s
				AND rating_date BETWEEN %(from_date)s AND %(to_date)s
			""",
			{
				"supplier": scorecard.supplier,
				"from_date": scorecard.start_date,
				"to_date": scorecard.end_date,
			},
		)

		return flt(average[0][0]) if average and average[0][0] is not None else 0.0

	except Exception:
		frappe.log_error(
			title="Scorecard portal rating failed",
			message=f"Supplier: {getattr(scorecard, 'supplier', None)}\n\n{frappe.get_traceback()}",
		)

		return 0.0

    