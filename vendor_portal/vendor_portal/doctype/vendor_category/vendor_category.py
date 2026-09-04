# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class VendorCategory(Document):
	"""Classification applied to every supplier in the portal.

	Carries the payment terms a category defaults to and the minimum vendor
	rating below which purchasing from that category is refused. Records are
	named by category_name, so the name is the natural key and duplicate
	category names are rejected by the framework rather than by validate().
	"""
	
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		category_name: DF.Data
		default_payment_terms: DF.Link | None
		description: DF.SmallText | None
		is_active: DF.Check
		minimum_rating_threshold: DF.Float
	# end: auto-generated types

	_DOCTYPE_NAME = "Vendor Category"
