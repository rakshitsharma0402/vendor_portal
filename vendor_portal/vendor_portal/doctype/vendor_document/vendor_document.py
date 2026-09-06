# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class VendorDocument(Document):
	"""A single supporting document attached to a vendor application.

	Verification is tracked per row rather than per application, so a reviewer
	can accept a GST certificate while a bank statement is still outstanding.
	verified_by is plain Data by design — it records who verified at the time
	and is deliberately not a Link, so a later User rename does not rewrite
	the audit trail.
	"""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		document_file: DF.Attach
		document_type: DF.Literal["GST Certificate", "PAN Card", "Bank Statement", "Trade License", "MSME Certificate", "Other"]
		is_verified: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		remarks: DF.SmallText | None
		verified_by: DF.Data | None
	# end: auto-generated types

	_DOCTYPE_NAME = "Vendor Document"
