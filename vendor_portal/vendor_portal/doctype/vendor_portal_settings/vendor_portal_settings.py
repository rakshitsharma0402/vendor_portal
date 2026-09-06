# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


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
