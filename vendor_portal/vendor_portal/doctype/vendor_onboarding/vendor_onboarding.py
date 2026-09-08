# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, validate_email_address
from frappe.model.workflow import apply_workflow

# 2-digit state code, 10-character PAN, 1 entity code, a literal Z, 1 check
# digit. The Z is fixed by the GSTIN specification, not a placeholder.
GST_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[0-9A-Z]{1}Z[0-9A-Z]{1}$")

# Five letters, four digits, one letter.
PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")

# An application in one of these states has a live claim on its GST number.
# Draft is excluded so two vendors can be typed up in parallel, and Rejected
# is excluded so a failed application does not block a corrected resubmission.
BLOCKING_STATUSES = ("Under Review", "Approved")

# Roles permitted to decide on an application. Purchase Manager carries
# ERPNext's buying authority; Vendor Manager is this portal's own governance
# role, and either is sufficient — vendor standing and purchasing authority
# overlap in practice but are not the same job.
DECISION_ROLES = ("Purchase Manager", "Vendor Manager")


class VendorOnboarding(Document):
	"""A vendor's application to be traded with.

	Submittable because an application is a real decision point: a draft is
	still being assembled, a submitted record is under review and locked
	against edits, and only an approved record produces an ERPNext Supplier.

	Validation is split deliberately. Format rules run on every save, because
	a malformed identifier is wrong the moment it is typed. Completeness and
	uniqueness rules run at submit, because a draft the applicant is still
	assembling must remain saveable — a draft that cannot be saved cannot be
	returned to.
	"""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from vendor_portal.vendor_portal.doctype.vendor_document.vendor_document import VendorDocument

		address_line_1: DF.Data
		amended_from: DF.Link | None
		bank_account_number: DF.Data | None
		bank_name: DF.Data | None
		city: DF.Data
		company_name: DF.Data
		contact_person: DF.Data | None
		documents: DF.Table[VendorDocument]
		email: DF.Data
		gst_number: DF.Data | None
		ifsc_code: DF.Data | None
		last_reminded_on: DF.Date | None
		linked_supplier: DF.Link | None
		naming_series: DF.Literal["VOB-.YYYY.-.#####"]
		onboarding_status: DF.Literal["Draft", "Under Review", "Approved", "Rejected"]
		pan_number: DF.Data | None
		phone: DF.Data
		pincode: DF.Data | None
		rejection_reason: DF.SmallText | None
		review_date: DF.Datetime | None
		reviewed_by: DF.Link | None
		state: DF.Data
		supplier_name: DF.Data
		vendor_category: DF.Link
	# end: auto-generated types

	_DOCTYPE_NAME = "Vendor Onboarding"


	def validate(self):
		"""Run the rules that apply to every save, including drafts.

		Raises:
			frappe.ValidationError: If GST, PAN or email are malformed.
		"""
		self.normalise_identifiers()
		self.validate_gst_number()
		self.validate_pan_number()
		self.validate_email()


	def before_submit(self):
		"""Run the rules that only apply once the application is complete.

		Raises:
			frappe.ValidationError: If a required GST number is missing, too
				few documents are attached, or the GST number is already
				claimed by another live application.
		"""
		self.validate_gst_required()
		self.validate_minimum_documents()
		self.validate_duplicate_gst()


	def on_update_after_submit(self):
		"""React to a state change on a submitted application.

		The side effects of a decision live here rather than in the endpoints
		because a workflow transition writes a field and nothing else. Hanging
		them off the field means the Actions menu, the API and any other route
		to Approved all produce the same result, instead of the menu quietly
		producing an approved application with no supplier behind it.
		"""
		if self.onboarding_status == "Approved":
			self.create_linked_supplier()
		elif self.onboarding_status == "Rejected":
			self.validate_rejection_reason()


	def create_linked_supplier(self):
		"""Create the Supplier this application describes, once.

		Guarded on linked_supplier rather than on supplier name: two vendors
		may legitimately share a name, but one application must never produce
		two suppliers. The guard is load-bearing — this method runs on every
		update to an approved record, not only on the transition into it.
		"""
		if self.linked_supplier:
			return

		supplier_name = _create_supplier(self)

		if supplier_name:
			self.db_set("linked_supplier", supplier_name)

		self.db_set(
			{
				"reviewed_by": frappe.session.user,
				"review_date": now_datetime(),
			}
		)

		_notify_applicant(self, approved=True)


	def validate_rejection_reason(self):
		"""Require a reason on a rejected application.

		Enforced on the document rather than only in the reject endpoint, so a
		rejection made through the workflow Actions menu cannot skip it.

		Raises:
			frappe.ValidationError: If rejection_reason is empty.
		"""
		if not (self.rejection_reason or "").strip():
			frappe.throw(
				_("A reason is required to reject an application."),
				title=_("Reason Missing"),
			)

		if not self.reviewed_by:
			self.db_set(
				{
					"reviewed_by": frappe.session.user,
					"review_date": now_datetime(),
				}
			)

			_notify_applicant(self, approved=False)


	def normalise_identifiers(self):
		"""Uppercase GST and PAN before they are checked or stored.

		Both are case-insensitive in practice but conventionally written in
		upper case. Normalising first means the patterns below need no case
		folding, and the duplicate check compares like with like rather than
		treating the same number typed two ways as two numbers.
		"""
		if self.gst_number:
			self.gst_number = self.gst_number.strip().upper()

		if self.pan_number:
			self.pan_number = self.pan_number.strip().upper()


	def validate_gst_number(self):
		"""Reject a malformed GST number.

		A blank value passes here; whether GST is required at all is a
		configuration question answered at submit.

		Raises:
			frappe.ValidationError: If gst_number is present and malformed.
		"""
		if not self.gst_number:
			return

		if not GST_PATTERN.match(self.gst_number):
			frappe.throw(
				_("{0} is not a valid GST number.").format(frappe.bold(self.gst_number)),
				title=_("Invalid GST Number"),
			)


	def validate_pan_number(self):
		"""Reject a malformed PAN number.

		Raises:
			frappe.ValidationError: If pan_number is present and malformed.
		"""
		if not self.pan_number:
			return

		if not PAN_PATTERN.match(self.pan_number):
			frappe.throw(
				_("{0} is not a valid PAN number.").format(frappe.bold(self.pan_number)),
				title=_("Invalid PAN Number"),
			)


	def validate_email(self):
		"""Reject a malformed email address.

		The email field carries the Email option, so the framework already
		checks this on save. Repeated here so the rule survives someone
		removing that option in Customize Form without realising the
		onboarding flow depended on it.

		Raises:
			frappe.ValidationError: If email is not a valid address.
		"""
		if not self.email:
			return

		validate_email_address(self.email, throw=True)


	def validate_gst_required(self):
		"""Require a GST number when the site is configured to expect one.

		Read from Vendor Portal Settings rather than hardcoded, so a site
		trading with unregistered vendors can turn it off without a
		deployment.

		Raises:
			frappe.ValidationError: If GST is required and none was given.
		"""
		if not frappe.db.get_single_value("Vendor Portal Settings", "require_gst_verification"):
			return

		if not self.gst_number:
			frappe.throw(
				_("A GST number is required to submit this application."),
				title=_("GST Number Missing"),
			)


	def validate_minimum_documents(self):
		"""Require the configured number of supporting documents at submit.

		Enforced here rather than in validate() so a part-filled draft can
		still be saved and returned to.

		Raises:
			frappe.ValidationError: If fewer document rows are attached than
				Vendor Portal Settings requires.
		"""
		minimum = frappe.db.get_single_value("Vendor Portal Settings", "min_documents_required") or 0

		attached = len(self.documents or [])

		if attached < minimum:
			frappe.throw(
				_("At least {0} supporting documents are required. This application has {1}.").format(
					minimum, attached
				),
				title=_("Missing Documents"),
			)


	def validate_duplicate_gst(self):
		"""Reject a GST number already claimed by another live application.

		Only Under Review and Approved applications block: a draft has not
		been committed to, and a rejected one must not stop the vendor
		resubmitting a corrected version.

		The record's own name and the record it amends are excluded, so
		amending a rejected application does not collide with itself.

		Note: Suppliers created outside this portal are not covered. A plain
		ERPNext v16 Supplier has no GST field, so there is nothing to compare
		against — the portal can only enforce uniqueness across what it owns.

		Raises:
			frappe.ValidationError: If another live application holds this GST
				number.
		"""
		if not self.gst_number:
			return

		excluded = [self.name]
		if self.amended_from:
			excluded.append(self.amended_from)

		duplicate = frappe.db.get_value(
			"Vendor Onboarding",
			{
				"gst_number": self.gst_number,
				"onboarding_status": ("in", BLOCKING_STATUSES),
				"docstatus": ("!=", 2),
				"name": ("not in", excluded),
			},
			"name",
		)

		if duplicate:
			frappe.throw(
				_("GST number {0} is already used by application {1}.").format(
					frappe.bold(self.gst_number), frappe.bold(duplicate)
				),
				title=_("Duplicate GST Number"),
			)


@frappe.whitelist()
def approve_onboarding(onboarding_name: str) -> dict:
	"""Approve an application through the workflow.

	Drives the workflow transition rather than writing the status directly, so
	an API approval passes the same legality and role checks a reviewer using
	the Actions menu passes, and triggers the same supplier creation.

	Args:
		onboarding_name: Name of the Vendor Onboarding record to approve.

	Returns:
		A dict with the onboarding name, its new status, and the Supplier
		created, or None when automatic creation is switched off.

	Raises:
		frappe.PermissionError: If the caller holds no deciding role.
		frappe.ValidationError: If Approve is not a legal transition from the
			application's current state.
	"""
	try:
		_check_decision_permission()

		doc = frappe.get_doc("Vendor Onboarding", onboarding_name)
		apply_workflow(doc, "Approve")

		return {
			"onboarding": doc.name,
			"status": doc.onboarding_status,
			"supplier": doc.linked_supplier,
		}

	except Exception:
		frappe.log_error(title="Vendor onboarding approval failed")
		raise


@frappe.whitelist()
def reject_onboarding(onboarding_name: str, reason: str) -> dict:
	"""Reject an application through the workflow and record why.

	The reason is written before the transition, because the document refuses
	to enter Rejected without one.

	Args:
		onboarding_name: Name of the Vendor Onboarding record to reject.
		reason: Why the application was refused.

	Returns:
		A dict with the onboarding name and its new status.

	Raises:
		frappe.PermissionError: If the caller holds no deciding role.
		frappe.ValidationError: If no reason was given, or Reject is not a
			legal transition from the current state.
	"""
	try:
		_check_decision_permission()

		if not (reason or "").strip():
			frappe.throw(
				_("A reason is required to reject an application."),
				title=_("Reason Missing"),
			)

		doc = frappe.get_doc("Vendor Onboarding", onboarding_name)
		doc.db_set("rejection_reason", reason.strip())
		doc.reload()

		apply_workflow(doc, "Reject")

		return {"onboarding": doc.name, "status": doc.onboarding_status}

	except Exception:
		frappe.log_error(title="Vendor onboarding rejection failed")
		raise


def _check_decision_permission():
	"""Refuse callers who hold no deciding role.

	Checked explicitly rather than left to DocType permissions: these are
	whitelisted endpoints reachable over HTTP, and write access to the
	onboarding record is not the same thing as authority to approve a vendor.

	Raises:
		frappe.PermissionError: If the caller holds none of DECISION_ROLES.
	"""
	if not set(DECISION_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Only a Purchase Manager can decide on vendor applications."),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)


def _create_supplier(doc) -> str | None:
	"""Create the ERPNext Supplier an approved application describes.

	Returns None without creating anything when automatic creation is switched
	off in Vendor Portal Settings, so a site that prefers to create suppliers
	by hand can still use the approval flow.

	Bank details are deliberately not copied: ERPNext holds supplier banking in
	a separate Bank Account document, not on Supplier, so carrying them across
	means creating a second record and is left to its own change.

	Args:
		doc: The approved Vendor Onboarding document.

	Returns:
		The new Supplier's name, or None when creation is switched off.
	"""
	settings = frappe.get_single("Vendor Portal Settings")

	if not settings.auto_create_supplier:
		return None

	supplier = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": doc.supplier_name,
			"supplier_group": settings.default_supplier_group,
			"custom_vendor_category": doc.vendor_category,
			"custom_onboarding_reference": doc.name,
		}
	)

	# The approving user needs authority over vendors, not over every field
	# ERPNext validates on a Supplier. The decision has already been
	# permission-checked above.
	supplier.insert(ignore_permissions=True)

	return supplier.name


def _notify_applicant(doc, approved: bool):
	"""Tell the applicant what was decided.

	Queued rather than sent inline, and failures are swallowed: the decision
	and the Supplier it created are already committed, and an unreachable mail
	server must not roll back an approval that otherwise succeeded.

	Args:
		doc: The decided Vendor Onboarding document.
		approved: True for an approval, False for a rejection.
	"""
	if not doc.email:
		return

	if approved:
		subject = _("Your vendor application has been approved")
		message = _("Your application {0} has been approved. We look forward to working with you.").format(
			doc.name
		)
	else:
		subject = _("Your vendor application was not approved")
		message = _("Your application {0} was not approved. Reason: {1}").format(
			doc.name, doc.rejection_reason
		)

	try:
		frappe.sendmail(
			recipients=[doc.email],
			subject=subject,
			message=message,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)
	except Exception:
		frappe.log_error(
			title="Vendor onboarding notification failed",
			message=f"Application: {doc.name}\n\n{frappe.get_traceback()}",
		)

		