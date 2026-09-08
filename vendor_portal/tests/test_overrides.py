# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Tests for the Purchase Order controller override and the Purchase Receipt hooks.

Both are tested here rather than in separate files because a receipt test needs
an order to receive against, and splitting them would duplicate the builder
setup that dominates this module.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from vendor_portal.tests.utils import (
	make_purchase_order,
	make_purchase_receipt,
	make_supplier,
)


class IntegrationTestPurchaseOverrides(IntegrationTestCase):
	"""Vendor standing gates, automatic pricing scores, and delivery scores."""

	def test_blacklisted_supplier_blocks_po(self):
		"""An order for a blacklisted supplier is refused at save."""
		supplier = make_supplier(
			custom_is_blacklisted=1, custom_blacklist_reason="Quality failures"
		)

		with self.assertRaises(frappe.ValidationError):
			make_purchase_order(supplier.name, submit=False)

	def test_low_rating_blocks_po(self):
		"""A supplier below its category's threshold cannot receive an order."""
		supplier = make_supplier(custom_vendor_category="Raw Materials")

		# 0.4 of the Rating field's range is 2.0 out of five, under Raw
		# Materials' threshold of 3.0.
		frappe.db.set_value(
			"Supplier",
			supplier.name,
			{"custom_vendor_rating": 0.4, "custom_total_rating_count": 3},
		)

		with self.assertRaises(frappe.ValidationError):
			make_purchase_order(supplier.name, submit=False)

	def test_unrated_supplier_allowed(self):
		"""A supplier with no ratings is not blocked.

		A vendor cannot earn a rating without first receiving an order, so
		treating an absent rating as a failing one would make every new
		supplier permanently unorderable.
		"""
		supplier = make_supplier(custom_vendor_category="Raw Materials")

		order = make_purchase_order(supplier.name, submit=False)

		self.assertTrue(frappe.db.exists("Purchase Order", order.name))

	def test_rating_scale_conversion_applied(self):
		"""A stored 0.8 passes a threshold expressed as 3 out of five.

		The Rating field holds a fraction and the threshold holds a score. If
		the two were compared directly, 0.8 would read as below 3 and every
		rated supplier would be blocked.
		"""
		supplier = make_supplier(custom_vendor_category="Raw Materials")

		frappe.db.set_value(
			"Supplier",
			supplier.name,
			{"custom_vendor_rating": 0.8, "custom_total_rating_count": 3},
		)

		order = make_purchase_order(supplier.name, submit=False)

		self.assertTrue(frappe.db.exists("Purchase Order", order.name))

	def test_po_submit_creates_pricing_rating(self):
		"""Submitting an order records exactly one pricing rating."""
		supplier = make_supplier()

		order = make_purchase_order(supplier.name)

		ratings = frappe.get_all(
			"Vendor Rating Log",
			filters={"purchase_order": order.name},
			fields=["rating_type", "score"],
		)

		self.assertEqual(len(ratings), 1)
		self.assertEqual(ratings[0].rating_type, "Pricing")

	def test_first_po_scores_neutral(self):
		"""A supplier's first order takes the neutral score.

		There is no history to compare against, and scoring it well or badly
		would reward or punish an average of one.
		"""
		supplier = make_supplier()

		order = make_purchase_order(supplier.name)

		score = frappe.db.get_value(
			"Vendor Rating Log", {"purchase_order": order.name}, "score"
		)

		self.assertEqual(score, 4.0)

	def test_cheaper_po_scores_higher(self):
		"""An order well below the supplier's average scores above neutral."""
		supplier = make_supplier()

		make_purchase_order(supplier.name, qty=10, rate=1000)

		cheaper = make_purchase_order(supplier.name, qty=10, rate=100)

		score = frappe.db.get_value(
			"Vendor Rating Log", {"purchase_order": cheaper.name}, "score"
		)

		self.assertEqual(score, 5.0)

	def test_po_cancel_deletes_rating(self):
		"""Cancelling an order withdraws the rating it produced.

		A cancelled order left rated would keep influencing every average
		computed for that supplier afterwards.
		"""
		supplier = make_supplier()

		order = make_purchase_order(supplier.name)

		self.assertTrue(frappe.db.exists("Vendor Rating Log", {"purchase_order": order.name}))

		order.cancel()

		self.assertFalse(frappe.db.exists("Vendor Rating Log", {"purchase_order": order.name}))

	def test_pr_submit_creates_delivery_rating(self):
		"""Submitting a receipt records one delivery rating."""
		supplier = make_supplier()

		order = make_purchase_order(supplier.name)
		receipt = make_purchase_receipt(order)

		ratings = frappe.get_all(
			"Vendor Rating Log",
			filters={"purchase_receipt": receipt.name},
			fields=["rating_type", "score"],
		)

		self.assertEqual(len(ratings), 1)
		self.assertEqual(ratings[0].rating_type, "Delivery")

	def test_short_delivery_scores_lower(self):
		"""A receipt below 90% of the ordered quantity scores below a full one.

		Compared against a complete delivery rather than asserted as an
		absolute: the score also depends on timeliness, which is computed from
		the run date, and pinning a number would break whenever the calendar
		moved.
		"""
		supplier = make_supplier()

		full_order = make_purchase_order(supplier.name, qty=10)
		full_receipt = make_purchase_receipt(full_order)

		short_order = make_purchase_order(supplier.name, qty=10)
		short_receipt = make_purchase_receipt(short_order, received_qty=5)

		full_score = frappe.db.get_value(
			"Vendor Rating Log", {"purchase_receipt": full_receipt.name}, "score"
		)
		short_score = frappe.db.get_value(
			"Vendor Rating Log", {"purchase_receipt": short_receipt.name}, "score"
		)

		self.assertLess(short_score, full_score)

	def test_delivery_rating_not_duplicated(self):
		"""Rating a receipt a second time produces no second log.

		The guard lives in the rating function rather than its callers, so the
		submit hook and the hourly backfill are both covered.
		"""
		from vendor_portal.overrides.purchase_receipt import create_delivery_rating

		supplier = make_supplier()

		order = make_purchase_order(supplier.name)
		receipt = make_purchase_receipt(order)

		create_delivery_rating(receipt)

		self.assertEqual(
			frappe.db.count("Vendor Rating Log", {"purchase_receipt": receipt.name}), 1
		)

        