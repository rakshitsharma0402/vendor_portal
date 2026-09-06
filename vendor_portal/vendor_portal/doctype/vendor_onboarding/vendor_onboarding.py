# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import validate_email_address

# 2-digit state code, 10-character PAN, 1 entity code, a literal Z, 1 check
# digit. The Z is fixed by the GSTIN specification, not a placeholder.
GST_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[0-9A-Z]{1}Z[0-9A-Z]{1}$")

# Five letters, four digits, one letter.
PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")

# An application in one of these states has a live claim on its GST number.
# Draft is excluded so two vendors can be typed up in parallel, and Rejected
# is excluded so a failed application does not block a corrected resubmission.
BLOCKING_STATUSES = ("Under Review", "Approved")

class VendorOnboarding(Document):
	"""A vendor's application to be traded with.

	Submittable because an application is a real decision point: a draft is
	still being assembled, a submitted record is under review and locked
	against edits, and only an approved record produces an ERPNext Supplier.

	Validation, the approve and reject transitions, and the Supplier creation
	they trigger are deliberately absent here — this doctype is schema only.
	Status is written by those transitions, never typed by a user, which is
	why every review field is read-only.
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

			