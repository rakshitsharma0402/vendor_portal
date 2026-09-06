# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class VendorRatingLog(Document):
	"""A single scored observation about a supplier.

	Vendor performance is derived from these entries rather than stored as one
	editable number, so a rating always traces back to the event that produced
	it — a receipt that arrived short, a price compared against history.

	Entries are intentionally not unique per supplier, type and date: one
	supplier can be rated twice in a day by two different receipts. Jobs that
	must not double-rate check the source document instead.
	"""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		naming_series: DF.Literal["VRL-.YYYY.-.#####"]
		purchase_order: DF.Link | None
		purchase_receipt: DF.Link | None
		rated_by: DF.Link | None
		rating_date: DF.Date | None
		rating_type: DF.Literal["Delivery", "Quality", "Pricing", "Communication"]
		remarks: DF.SmallText | None
		score: DF.Float
		supplier: DF.Link
	# end: auto-generated types

	_DOCTYPE_NAME = "Vendor Rating Log"