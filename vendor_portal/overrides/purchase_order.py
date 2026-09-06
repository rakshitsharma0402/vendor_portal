# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erpnext.buying.doctype.purchase_order.purchase_order import PurchaseOrder

from vendor_portal.utils import rating_field_to_scale

# How far a PO's value may sit from the supplier's average before it counts as
# cheap or expensive rather than typical.
PRICING_BAND = 0.10

SCORE_CHEAPER = 5.0
SCORE_TYPICAL = 4.0
SCORE_EXPENSIVE = 3.0


class CustomPurchaseOrder(PurchaseOrder):
	"""Purchase Order with vendor standing enforced at save and scored at submit.

	Extends ERPNext's controller rather than hooking doc_events because these
	rules are part of what a Purchase Order *is* in this business: an order to
	a blacklisted or underperforming vendor is not a valid order. doc_events
	would express the same behaviour as something bolted alongside the
	document, and could not participate in the controller's own method
	resolution if a later rule needed to build on ERPNext's.
	"""


	def validate(self):
		"""Apply ERPNext's validation, then the vendor standing gates.

		super() runs first so ERPNext has established supplier, currency, item
		rates and totals before anything here reads them — and so a document
		ERPNext itself considers invalid never reaches these checks.

		Raises:
			frappe.ValidationError: If the supplier is blacklisted or rated
				below its category's threshold.
		"""
		super().validate()

		self.block_blacklisted_supplier()
		self.block_underrated_supplier()

		frappe.logger("vendor_portal").info(
			f"PO {self.name} validated for supplier {self.supplier}"
		)


	def on_submit(self):
		"""Submit through ERPNext, then record how this order was priced.

		super() runs first because the rating describes a committed order; if
		ERPNext refuses the submission there is nothing to rate.
		"""
		super().on_submit()

		self.create_pricing_rating()


	def on_cancel(self):
		"""Cancel through ERPNext, then withdraw the ratings this order caused.

		super() runs first so ERPNext's own cancellation checks — linked
		receipts, invoices — decide whether the cancellation happens at all
		before any rating is removed.
		"""
		super().on_cancel()

		self.delete_linked_ratings()


	def block_blacklisted_supplier(self):
		"""Refuse orders to a blacklisted supplier.

		Raises:
			frappe.ValidationError: If the supplier is blacklisted.
		"""
		is_blacklisted, blacklist_reason = frappe.db.get_value(
			"Supplier", self.supplier, ["custom_is_blacklisted", "custom_blacklist_reason"]
		)

		if not is_blacklisted:
			return

		frappe.throw(
			_("Cannot create Purchase Order for blacklisted supplier {0}. Reason: {1}").format(
				frappe.bold(self.supplier_name or self.supplier),
				blacklist_reason or _("not recorded"),
			),
			title=_("Supplier Blacklisted"),
		)


	def block_underrated_supplier(self):
		"""Refuse orders to a supplier scoring below its category's threshold.

		A supplier with no ratings yet passes. A newly onboarded vendor has no
		history by definition, and blocking it would mean no vendor could ever
		receive the first order that would give it one.

		Raises:
			frappe.ValidationError: If the supplier is rated below its
				category's minimum.
		"""
		supplier = frappe.db.get_value(
			"Supplier",
			self.supplier,
			["custom_vendor_category", "custom_vendor_rating", "custom_total_rating_count"],
			as_dict=True,
		)

		if not supplier or not supplier.custom_vendor_category:
			return

		if not supplier.custom_total_rating_count:
			return

		threshold = frappe.db.get_value(
			"Vendor Category", supplier.custom_vendor_category, "minimum_rating_threshold"
		)

		if not threshold:
			return

		# The Rating field stores 0-1; the threshold is on the 1-5 scale.
		rating = rating_field_to_scale(supplier.custom_vendor_rating)
		
		if rating >= threshold:
			return

		frappe.throw(
			_("Supplier {0} rating ({1}) is below the minimum threshold ({2}) for {3}.").format(
				frappe.bold(self.supplier_name or self.supplier),
				frappe.format_value(rating, {"fieldtype": "Float", "precision": 2}),
				frappe.format_value(threshold, {"fieldtype": "Float", "precision": 2}),
				supplier.custom_vendor_category,
			),
			title=_("Supplier Below Rating Threshold"),
		)


	def create_pricing_rating(self):
		"""Score this order against what the supplier usually charges.

		Cheaper than typical earns a better score, more expensive a worse one.
		A first order has nothing to compare against and takes the neutral
		score rather than being rewarded or punished for an average of one.
		"""
		average = self.get_average_order_value()

		if not average:
			score = SCORE_TYPICAL
		elif self.grand_total < average * (1 - PRICING_BAND):
			score = SCORE_CHEAPER
		elif self.grand_total > average * (1 + PRICING_BAND):
			score = SCORE_EXPENSIVE
		else:
			score = SCORE_TYPICAL

		rating = frappe.get_doc(
			{
				"doctype": "Vendor Rating Log",
				"supplier": self.supplier,
				"purchase_order": self.name,
				"rating_type": "Pricing",
				"score": score,
				"remarks": _("Automatic pricing score on order submission."),
			}
		)

		# The buyer has authority over the order, not necessarily over rating
		# records; the rating is the system's observation, not theirs.
		rating.insert(ignore_permissions=True)


	def get_average_order_value(self) -> float | None:
		"""Return the supplier's mean submitted order value, excluding this one.

		This order is excluded so the first PO for a supplier compares against
		nothing and takes the neutral score by rule, rather than comparing
		against itself and landing on neutral by accident.

		Returns:
			The mean grand_total of the supplier's other submitted orders, or
			None when there are none.
		"""
		result = frappe.db.sql(
			"""
			SELECT AVG(grand_total)
			FROM `tabPurchase Order`
			WHERE supplier = %(supplier)s
				AND docstatus = 1
				AND name != %(name)s
			""",
			{"supplier": self.supplier, "name": self.name},
		)

		return result[0][0] if result and result[0][0] else None


	def delete_linked_ratings(self):
		"""Remove the rating logs this order produced.

		Leaving them behind would keep a cancelled order influencing every
		average computed for this supplier afterwards. Deletes nothing when
		there is nothing to delete, so a re-cancellation is harmless.
		"""
		for name in frappe.get_all(
			"Vendor Rating Log", filters={"purchase_order": self.name}, pluck="name"
		):
			frappe.delete_doc("Vendor Rating Log", name, ignore_permissions=True)

            