# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Tests for the row-level access rules.

Every test here runs as somebody other than Administrator, who bypasses both
rules entirely — testing them as Administrator would pass while proving
nothing. The session user is restored in tearDown rather than at the end of
each test, so a failing assertion cannot leave the suite running as the wrong
person.
"""

import frappe
from frappe.tests import IntegrationTestCase

from vendor_portal.tests.utils import make_onboarding, make_supplier

PURCHASE_USER = "test_purchase_user@example.com"
VENDOR_MANAGER = "test_vendor_mgr@example.com"


class IntegrationTestVendorPortalPermissions(IntegrationTestCase):
	"""Rating authorship and onboarding visibility."""

	def tearDown(self):
		"""Return to Administrator whatever the test did.

		In tearDown rather than a finally block in each test: an assertion
		that fails partway leaves the session as another user, and every test
		afterwards then fails for reasons unrelated to what it asserts.
		"""
		frappe.set_user("Administrator")

	def _make_rating(self, supplier: str, rated_by: str) -> str:
		"""Create a rating log attributed to a given user.

		Args:
			supplier: The supplier being rated.
			rated_by: Who the rating belongs to.

		Returns:
			The log's name.
		"""
		log = frappe.get_doc(
			{
				"doctype": "Vendor Rating Log",
				"supplier": supplier,
				"rating_type": "Quality",
				"score": 3,
			}
		)

		log.insert(ignore_permissions=True)

		frappe.db.set_value("Vendor Rating Log", log.name, "rated_by", rated_by)

		return log.name

	def test_own_ratings_only(self):
		"""A user can change their own rating and not somebody else's."""
		supplier = make_supplier()

		mine = self._make_rating(supplier.name, PURCHASE_USER)
		theirs = self._make_rating(supplier.name, VENDOR_MANAGER)

		frappe.set_user(PURCHASE_USER)

		own = frappe.get_doc("Vendor Rating Log", mine)
		own.remarks = "my own note"
		own.save()

		other = frappe.get_doc("Vendor Rating Log", theirs)
		other.remarks = "not mine to change"

		with self.assertRaises(frappe.PermissionError):
			other.save()

	def test_reading_others_ratings_is_allowed(self):
		"""Reading is not restricted, only changing.

		A team that cannot see each other's ratings cannot compare vendors,
		and the dashboard would report a different average to every user.
		"""
		supplier = make_supplier()
		theirs = self._make_rating(supplier.name, VENDOR_MANAGER)

		frappe.set_user(PURCHASE_USER)

		doc = frappe.get_doc("Vendor Rating Log", theirs)

		self.assertEqual(doc.name, theirs)

	def test_manager_edits_any_rating(self):
		"""A vendor manager can change a rating somebody else authored."""
		supplier = make_supplier()
		theirs = self._make_rating(supplier.name, PURCHASE_USER)

		frappe.set_user(VENDOR_MANAGER)

		doc = frappe.get_doc("Vendor Rating Log", theirs)
		doc.remarks = "reviewed by a manager"
		doc.save()

		self.assertEqual(doc.remarks, "reviewed by a manager")

	def test_onboarding_list_filtered_by_owner(self):
		"""A purchase team user sees only the applications they created.

		Asserted through frappe.get_list, which is the call
		permission_query_conditions applies to — frappe.get_all bypasses
		permissions by design, so a test using it would pass while proving
		nothing.
		"""
		frappe.set_user(PURCHASE_USER)

		mine = make_onboarding(supplier_name="Owned By Purchase User")

		frappe.set_user("Administrator")

		theirs = make_onboarding(supplier_name="Owned By Administrator")

		frappe.set_user(PURCHASE_USER)

		visible = frappe.get_list("Vendor Onboarding", pluck="name")

		self.assertIn(mine.name, visible)
		self.assertNotIn(theirs.name, visible)

	def test_manager_sees_all_onboardings(self):
		"""A vendor manager is exempt from the ownership filter."""
		frappe.set_user(PURCHASE_USER)

		theirs = make_onboarding(supplier_name="Owned By Purchase User")

		frappe.set_user(VENDOR_MANAGER)

		visible = frappe.get_list("Vendor Onboarding", pluck="name")

		self.assertIn(theirs.name, visible)

	def test_summary_endpoint_respects_row_level_filter(self):
		"""The pipeline summary counts only what the caller may see."""
		from vendor_portal.api import get_onboarding_status_summary

		frappe.set_user("Administrator")
		theirs = make_onboarding(supplier_name="Owned By Administrator")

		frappe.set_user(PURCHASE_USER)
		mine = make_onboarding(supplier_name="Owned By Purchase User")

		summary = get_onboarding_status_summary()
		names = [row["name"] for row in summary["recent_submissions"]]

		# Asserted by membership rather than by count: applications created by
		# earlier tests in this class survive the rollback, so an absolute
		# number would depend on execution order.
		self.assertIn(mine.name, names)
		self.assertNotIn(theirs.name, names)

        