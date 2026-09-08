# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Tests for the whitelisted endpoints.

These run as Administrator and assert values. Access rules are tested
separately, in test_permissions, because a test that changes the session user
and fails before restoring it would make every test after it report a problem
that is not there.
"""

import frappe
from frappe.tests import IntegrationTestCase

from vendor_portal.api import (
	get_supplier_comparison,
	get_vendor_dashboard,
	submit_vendor_rating,
)
from vendor_portal.tests.utils import make_item, make_purchase_order, make_supplier


class IntegrationTestVendorPortalAPI(IntegrationTestCase):
	"""Rating submission, dashboard aggregation and supplier comparison."""

	def test_vendor_rating_recalculation(self):
		"""Two equally weighted ratings average to the midpoint between them.

		Delivery and quality both weigh 0.3 by default, so 5 and 1 give 3.0.
		Asserted as an exact figure rather than a range: if the weighting
		changes, this should fail rather than quietly still passing.
		"""
		supplier = make_supplier()

		submit_vendor_rating(supplier.name, "Delivery", 5)
		result = submit_vendor_rating(supplier.name, "Quality", 1)

		self.assertAlmostEqual(result["rating"], 3.0, places=2)
		self.assertEqual(result["rating_count"], 2)

	def test_renormalisation_across_present_types(self):
		"""A single delivery rating of 5 reads as 5, not as a fraction of four.

		The weights are renormalised across the types that have entries. Were
		they not, a vendor rated five on its only measured dimension would
		read as 1.5 — punished for the three nobody has scored.
		"""
		supplier = make_supplier()

		result = submit_vendor_rating(supplier.name, "Delivery", 5)

		self.assertAlmostEqual(result["rating"], 5.0, places=2)

	def test_rating_written_as_fraction(self):
		"""The Supplier field stores the 0-1 equivalent of the score."""
		supplier = make_supplier()

		submit_vendor_rating(supplier.name, "Delivery", 4)

		stored = frappe.db.get_value("Supplier", supplier.name, "custom_vendor_rating")

		self.assertAlmostEqual(stored, 0.8, places=2)

	def test_invalid_score_rejected(self):
		"""A score outside 1-5 is refused before a log is created."""
		supplier = make_supplier()

		with self.assertRaises(frappe.ValidationError):
			submit_vendor_rating(supplier.name, "Delivery", 9)

		self.assertEqual(frappe.db.count("Vendor Rating Log", {"supplier": supplier.name}), 0)

	def test_invalid_rating_type_rejected(self):
		"""An unrecognised rating type is refused."""
		supplier = make_supplier()

		with self.assertRaises(frappe.ValidationError):
			submit_vendor_rating(supplier.name, "Punctuality", 3)

	def test_dashboard_counts_documents_once(self):
		"""Orders are counted once regardless of how many ratings exist.

		The figures come from separate queries rather than one join precisely
		to avoid this: joining orders and ratings would report two orders and
		three ratings as six of each.
		"""
		supplier = make_supplier()

		make_purchase_order(supplier.name)
		make_purchase_order(supplier.name)

		submit_vendor_rating(supplier.name, "Quality", 4)
		submit_vendor_rating(supplier.name, "Communication", 4)

		dashboard = get_vendor_dashboard(supplier.name)

		self.assertEqual(dashboard["total_pos"], 2)

	def test_dashboard_empty_supplier(self):
		"""A supplier with no history returns zeroes, not nulls."""
		supplier = make_supplier()

		dashboard = get_vendor_dashboard(supplier.name)

		self.assertEqual(dashboard["total_pos"], 0)
		self.assertEqual(dashboard["total_po_value"], 0)
		self.assertEqual(dashboard["avg_rating"], 0)
		self.assertEqual(dashboard["recent_ratings"], [])

	def test_supplier_comparison_orders_by_rating(self):
		"""The better-rated supplier of two appears first."""
		item = make_item()

		better = make_supplier()
		worse = make_supplier()

		make_purchase_order(better.name, item_code=item.item_code, rate=100)
		make_purchase_order(worse.name, item_code=item.item_code, rate=100)

		submit_vendor_rating(better.name, "Quality", 5)
		submit_vendor_rating(worse.name, "Quality", 2)

		comparison = get_supplier_comparison(item.item_code)
		suppliers = [row["supplier"] for row in comparison]

		self.assertLess(suppliers.index(better.name), suppliers.index(worse.name))

	def test_supplier_comparison_excludes_blacklisted(self):
		"""A blacklisted supplier is absent from the comparison.

		The endpoint exists to choose who to order from, and the purchase
		order controller refuses those orders anyway — offering an option that
		cannot be acted on wastes the reader's attention.
		"""
		item = make_item()

		supplier = make_supplier()
		make_purchase_order(supplier.name, item_code=item.item_code)

		frappe.db.set_value("Supplier", supplier.name, "custom_is_blacklisted", 1)

		comparison = get_supplier_comparison(item.item_code)

		self.assertNotIn(supplier.name, [row["supplier"] for row in comparison])

        