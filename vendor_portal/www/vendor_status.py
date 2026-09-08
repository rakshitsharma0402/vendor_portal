# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Public application status lookup.

Application names run in a series, so a name alone is guessable. The lookup
therefore requires the name and the email it was submitted with, and answers
identically whether the name is unknown or the email is wrong — otherwise the
difference between the two responses confirms which applications exist.
"""

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	"""Render the lookup form.

	Args:
		context: The page context Frappe renders with.
	"""
	context.no_cache = 1


@frappe.whitelist(allow_guest=True)
@frappe.rate_limit(limit=20, seconds=60 * 60)
def check_status(application: str, email: str) -> dict:
	"""Return an application's status to whoever submitted it.

	Both arguments must match. A correct name with the wrong email gives the
	same answer as a name that does not exist, so the endpoint cannot be used
	to discover which applications are real.

	Args:
		application: The application's name, given to the applicant on
			submission.
		email: The address the application was submitted with.

	Returns:
		Status, category and submission date. Never the reviewer, the
		rejection reason, or anything about another application.

	Raises:
		frappe.ValidationError: If either argument is missing, or the pair
			does not match an application.
	"""
	try:
		application = (application or "").strip()
		email = (email or "").strip().lower()

		if not application or not email:
			frappe.throw(
				_("Enter both your application reference and your email address."),
				title=_("Details Missing"),
			)

		record = frappe.db.get_value(
			"Vendor Onboarding",
			{"name": application, "email": email},
			["name", "onboarding_status", "vendor_category", "creation"],
			as_dict=True,
		)

		if not record:
			# Deliberately the same message for a wrong email as for an
			# unknown reference. Distinguishing them would turn this into a
			# way of confirming which applications exist.
			frappe.throw(
				_("No application matches that reference and email address."),
				title=_("Not Found"),
			)

		return {
			"application": record.name,
			"status": _(record.onboarding_status),
			"vendor_category": record.vendor_category,
			"submitted_on": frappe.format(record.creation, {"fieldtype": "Date"}),
		}

	except frappe.ValidationError:
		raise

	except Exception:
		frappe.log_error(
			title="Vendor status lookup failed",
			message=frappe.get_traceback(),
		)
		raise

    