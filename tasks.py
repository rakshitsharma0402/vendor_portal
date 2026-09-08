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


def _alert_if_newly_underperforming(supplier, previous, result, threshold):
	"""Email vendor managers when a supplier drops below the threshold.

	Only on the crossing. A vendor that has been underperforming for months is
	already known, and mailing about it every night trains the recipients to
	ignore the alert entirely — at which point the one that matters is missed
	too. The weekly digest is where standing problems are listed.

	Args:
		supplier: Name of the Supplier.
		previous: Its stored rating and count before recalculation.
		result: What recalculate_vendor_rating returned.
		threshold: The score below which a vendor is underperforming.
	"""
	if not threshold:
		return

	new_rating = flt(result.get("rating"))

	if not result.get("rating_count") or new_rating >= threshold:
		return

	# A supplier with no previous ratings has not crossed anything — it has
	# arrived. Treated as a crossing so a vendor whose first ratings are poor
	# is not silently accepted.
	previous_rating = rating_field_to_scale(previous.get("custom_vendor_rating"))
	had_ratings = bool(previous.get("custom_total_rating_count"))

	if had_ratings and previous_rating < threshold:
		return

	recipients = _get_vendor_manager_emails()

	if not recipients:
		return

	try:
		frappe.sendmail(
			recipients=recipients,
			subject=_("Vendor rating below threshold: {0}").format(supplier),
			message=_(
				"{0} has dropped to {1} out of 5, below the threshold of {2}. "
				"Purchase orders for this vendor may now be blocked."
			).format(supplier, round(new_rating, 2), threshold),
			reference_doctype="Supplier",
			reference_name=supplier,
			queue=True,
		)
	except Exception:
		# The rating is already correct and committed. A mail server that is
		# down must not undo a night's reconciliation.
		frappe.log_error(title="Low rating alert failed", message=f"Supplier: {supplier}")


def _get_vendor_manager_emails() -> list[str]:
	"""Return the addresses of every enabled user holding the Vendor Manager role.

	Returns:
		Email addresses, without duplicates.
	"""
	return frappe.db.sql_list(
		"""
		SELECT DISTINCT u.name
		FROM `tabUser` u
		INNER JOIN `tabHas Role` r ON r.parent = u.name
		WHERE r.role = %(role)s
			AND u.enabled = 1
			AND u.name NOT IN ('Administrator', 'Guest')
		""",
		{"role": "Vendor Manager"},
	)

