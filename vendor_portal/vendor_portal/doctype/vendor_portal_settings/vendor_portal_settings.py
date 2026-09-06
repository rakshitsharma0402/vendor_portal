# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# Binary floating point cannot represent 0.3 or 0.2 exactly, so the shipped
# defaults do not sum to precisely 1.0. Comparing against a tolerance keeps
# the defaults valid against their own rule.
WEIGHT_SUM_TOLERANCE = 0.001

MIN_RATING = 1.0
MAX_RATING = 5.0


class VendorPortalSettings(Document):
	"""Site-wide configuration for onboarding and vendor rating.

	Every rule that an administrator should be able to change without a
	deployment lives here: how many documents an application must carry, the
	weighting behind a supplier's overall rating, and the score below which a
	vendor is treated as underperforming.

	Controllers, background jobs and reports read these values rather than
	holding their own copies, so the weighting can be retuned in one place and
	take effect everywhere at once.
	"""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		auto_create_supplier: DF.Check
		auto_rating_enabled: DF.Check
		default_supplier_group: DF.Link | None
		low_rating_threshold: DF.Float
		min_documents_required: DF.Int
		rating_weight_communication: DF.Float
		rating_weight_delivery: DF.Float
		rating_weight_pricing: DF.Float
		rating_weight_quality: DF.Float
		require_gst_verification: DF.Check
	# end: auto-generated types

	_DOCTYPE_NAME = "Vendor Portal Settings"


	def validate(self):
		"""Run all validations for these settings.

		Raises:
			frappe.ValidationError: If the rating weights do not sum to 1.0,
				or if a threshold falls outside its usable range.
		"""
		self.validate_rating_weights()
		self.validate_thresholds()


	def validate_rating_weights(self):
		"""Reject weightings that do not sum to 1.0.

		Consumers multiply each rating type by its weight and add the results,
		so a total other than 1.0 silently scales every supplier's rating up or
		down. Rejecting it here means no consumer has to normalise, and the
		error appears where the number was typed rather than inside a job days
		later.

		Raises:
			frappe.ValidationError: If the four weights do not sum to 1.0
				within tolerance.
		"""
		total = (
			(self.rating_weight_delivery or 0)
			+ (self.rating_weight_quality or 0)
			+ (self.rating_weight_pricing or 0)
			+ (self.rating_weight_communication or 0)
		)

		if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
			frappe.throw(
				_("Rating weights must sum to 1.0. Current total: {0}.").format(
					frappe.format_value(total, {"fieldtype": "Float", "precision": 2})
				),
				title=_("Invalid Rating Weights"),
			)


	def validate_thresholds(self):
		"""Keep the onboarding and rating thresholds inside usable ranges.

		A negative document minimum makes the onboarding check vacuous, and a
		low-rating threshold outside the 1-5 scale can never be crossed, which
		would silently disable the underperformance alerts rather than
		reporting a misconfiguration.

		Raises:
			frappe.ValidationError: If min_documents_required is negative or
				low_rating_threshold falls outside 1-5.
		"""
		if (self.min_documents_required or 0) < 0:
			frappe.throw(
				_("Minimum documents required cannot be negative."),
				title=_("Invalid Setting"),
			)

		if not MIN_RATING <= (self.low_rating_threshold or 0) <= MAX_RATING:
			frappe.throw(
				_("Low rating threshold must be between {0} and {1}.").format(
					frappe.format_value(MIN_RATING, {"fieldtype": "Float", "precision": 0}),
					frappe.format_value(MAX_RATING, {"fieldtype": "Float", "precision": 0}),
				),
				title=_("Invalid Setting"),
			)

			