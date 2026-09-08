# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Scheduled jobs for the vendor portal.

Every job here must be safe to run twice. The scheduler retries, a developer
runs them by hand, and a job killed halfway will be started again from the
beginning — so each one either recomputes from source or checks whether its
work is already done before doing it.
"""

import frappe
from frappe import _
from frappe.utils import flt

from vendor_portal.utils import rating_field_to_scale, recalculate_vendor_rating


def recalculate_all_vendor_ratings():
	"""Reconcile every rated supplier's score with its rating log.

	Ratings reach the Supplier record two ways: the submission endpoint
	updates it immediately, and order and receipt submission create log
	entries without touching it. Cancellation removes entries the same way.
	This closes the gap nightly so the score a buyer sees is never more than a
	day behind what the log actually holds.

	Suppliers are committed one at a time rather than in a single transaction
	at the end: a job killed partway should leave the suppliers it already
	reconciled correct, not roll all of them back.
	"""
	threshold = flt(
		frappe.db.get_single_value("Vendor Portal Settings", "low_rating_threshold")
	)

	for supplier in _get_suppliers_to_recalculate():
		try:
			# Read before overwriting: the alert fires on the crossing, not on
			# the state, and this is the only moment the previous value exists.
			previous = frappe.db.get_value(
				"Supplier",
				supplier,
				["custom_vendor_rating", "custom_total_rating_count"],
				as_dict=True,
			)

			result = recalculate_vendor_rating(supplier)

			frappe.db.commit()

			_alert_if_newly_underperforming(supplier, previous, result, threshold)

		except Exception:
			# One bad supplier must not cost the rest of the run. Logged with
			# its name so the failure is findable rather than a silent gap.
			frappe.log_error(
				title="Vendor rating recalculation failed",
				message=f"Supplier: {supplier}",
			)


def _get_suppliers_to_recalculate() -> list[str]:
	"""Return the suppliers whose stored rating could be out of date.

	Two groups, and the second is the one that is easy to miss. Suppliers with
	rating logs obviously need recalculating. Suppliers with no logs but a
	non-zero stored count had their ratings deleted — by a cancelled order or
	receipt — and would otherwise keep a score nothing supports.

	Iterating every supplier would work but wastes a run on the majority that
	have never been rated at all.

	Returns:
		Supplier names, without duplicates.
	"""
	rated = frappe.db.sql_list(
		"""
		SELECT DISTINCT vrl.supplier
		FROM `tabVendor Rating Log` vrl
		INNER JOIN `tabSupplier` s ON s.name = vrl.supplier
		WHERE COALESCE(s.disabled, 0) = 0
		"""
	)

	stale = frappe.db.sql_list(
		"""
		SELECT name
		FROM `tabSupplier`
		WHERE COALESCE(disabled, 0) = 0
			AND COALESCE(custom_total_rating_count, 0) > 0
			AND name NOT IN (
				SELECT DISTINCT supplier FROM `tabVendor Rating Log`
			)
		"""
	)

	return list(dict.fromkeys([*rated, *stale]))

