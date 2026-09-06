# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


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
