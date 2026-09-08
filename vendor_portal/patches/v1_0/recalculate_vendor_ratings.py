# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Settle supplier ratings against the rating log at install time.

A site adopting this app may already hold rating logs, imported or created by
the purchase flow before the Supplier fields existed. Their scores would stay
at zero until the first nightly run — and for that first day the purchase
order rating gate reads every vendor as unrated and lets through orders it
should block.

The daily job would eventually do this. The patch exists so the site is
correct from the moment of install rather than from the following morning.
"""

import frappe

from vendor_portal.tasks import _get_suppliers_to_recalculate
from vendor_portal.utils import recalculate_vendor_rating


def execute():
	"""Recalculate every supplier whose stored rating could be out of date.

	The weighted formula is not restated here. It lives in
	vendor_portal.utils, the rating submission endpoint calls it, the daily
	job calls it, and so does this — one definition, so a change to the
	weighting cannot leave three implementations disagreeing.

	Alerts are deliberately not sent. The daily job mails vendor managers when
	a supplier crosses below the threshold; an install is not a crossing, and
	mailing about every underperforming vendor at once on a site where nobody
	has asked to be told would be a poor introduction.
	"""
	suppliers = _get_suppliers_to_recalculate()

	if not suppliers:
		print("No supplier ratings needed recalculating.")
		return

	updated = 0
	failed = []

	for supplier in suppliers:
		try:
			recalculate_vendor_rating(supplier)
			updated += 1
		except Exception:
			failed.append(supplier)

	print(f"Recalculated ratings for {updated} suppliers.")

	if failed:
		message = "Suppliers that could not be recalculated:\n" + "\n".join(failed)

		print(message)

		frappe.log_error(
			title="Vendor rating recalculation patch left suppliers unprocessed",
			message=message,
		)

	frappe.db.commit()

    