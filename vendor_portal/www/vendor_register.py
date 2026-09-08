# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Public vendor registration.

Guests reach this route without a Desk account, so nothing here relies on
DocType permissions. The endpoint constructs the document itself from an
allowlist of applicant-facing fields and inserts it with ignore_permissions —
one controlled entry point rather than granting Guest create access to Vendor
Onboarding, which would also open it to the REST API.
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

# Fields an applicant may set. An allowlist rather than a denylist: a denylist
# needs updating every time a field is added to the doctype, and the cost of
# forgetting is an applicant setting their own onboarding_status to Approved.
APPLICANT_FIELDS = (
	"supplier_name",
	"company_name",
	"email",
	"phone",
	"gst_number",
	"pan_number",
	"vendor_category",
	"contact_person",
	"address_line_1",
	"city",
	"state",
	"pincode",
	"bank_name",
	"bank_account_number",
	"ifsc_code",
)

no_cache = 1


def get_context(context):
	"""Provide the categories an applicant can choose from.

	Args:
		context: The page context Frappe renders with.
	"""
	context.no_cache = 1
	context.vendor_categories = frappe.get_all(
		"Vendor Category",
		filters={"is_active": 1},
		fields=["name"],
		order_by="name asc",
		ignore_permissions=True,
	)


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=5, seconds=60 * 60)
def submit_application(**kwargs) -> dict:
	"""Create a draft application from a public submission.

	Rate limited because this is an unauthenticated write: without a cap the
	form is a way to fill the review pipeline with noise.

	The document is constructed and inserted normally, so the controller's
	validation runs — a malformed GST is refused here exactly as it would be
	in Desk. The public path is not a weaker path.

	Args:
		**kwargs: Submitted fields. Anything outside APPLICANT_FIELDS is
			discarded rather than rejected, so a stray form field does not
			fail an otherwise valid application.

	Returns:
		The application's name, which the applicant needs to check its status.

	Raises:
		frappe.ValidationError: If the submission fails the same validation a
			Desk user would face.
	"""
	try:
		values = {
			field: (kwargs.get(field) or "").strip()
			for field in APPLICANT_FIELDS
			if (kwargs.get(field) or "").strip()
		}

		doc = frappe.get_doc({"doctype": "Vendor Onboarding", **values})

		# Inserted with permissions ignored because the caller has none — the
		# authority comes from this endpoint being the only way in, not from
		# the session.
		doc.insert(ignore_permissions=True)

		frappe.db.commit()

		return {
			"application": doc.name,
			"message": _(
				"Your application has been received. Keep reference {0} to check its status."
			).format(doc.name),
		}

	except frappe.ValidationError:
		# Validation messages are the applicant's to see — they say what to
		# correct. Re-raised rather than swallowed into a generic failure.
		raise

	except Exception:
		frappe.log_error(
			title="Vendor self-service registration failed",
			message=frappe.get_traceback(),
		)
		raise

    