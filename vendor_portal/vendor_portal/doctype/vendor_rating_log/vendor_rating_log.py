# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# Scores are on a 1-5 scale rather than 0-5: a zero would be indistinguishable
# from an unset Float when the weighted average is computed downstream.
MIN_SCORE = 1.0
MAX_SCORE = 5.0


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


	def validate(self):
		"""Run all validations for this rating log.

		Raises:
			frappe.ValidationError: If the score falls outside 1-5.
		"""
		self.validate_score_range()


	def validate_score_range(self):
		"""Reject scores outside the 1-5 scale.

		Float carries no bounds of its own, so the scale is enforced here
		rather than in the schema. Client-side checks are UX only; this is the
		authoritative gate, and it runs for API and background-job writes that
		never touch a form.

		Raises:
			frappe.ValidationError: If score is below 1 or above 5.
		"""
		if self.score is None:
			return

		if not MIN_SCORE <= self.score <= MAX_SCORE:
			frappe.throw(
				_("Score must be between {0} and {1}.").format(
					frappe.format_value(MIN_SCORE, {"fieldtype": "Float", "precision": 0}),
					frappe.format_value(MAX_SCORE, {"fieldtype": "Float", "precision": 0}),
				),
				title=_("Invalid Score"),
			)

			