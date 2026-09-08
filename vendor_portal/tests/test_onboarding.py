# Copyright (c) 2026, Rakshit Sharma and Contributors
# See license.txt

"""Tests for onboarding validation and the decision endpoints."""

import frappe
from frappe.tests import IntegrationTestCase

from vendor_portal.tests.utils import (
	get_settings_value,
	make_onboarding,
	set_settings_value,
	unique_gst,
)
from vendor_portal.vendor_portal.doctype.vendor_onboarding.vendor_onboarding import (
	approve_onboarding,
	reject_onboarding,
)


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list


class IntegrationTestVendorOnboarding(IntegrationTestCase):
	"""Validation rules and the approve and reject transitions."""

	def test_gst_validation_format(self):
		"""A malformed GST number is refused at save."""
		with self.assertRaises(frappe.ValidationError):
			make_onboarding(gst_number="27AAACM1234C1Z")

	def test_gst_normalised_to_uppercase(self):
		"""A lowercase GST number is stored uppercased."""
		doc = make_onboarding(gst_number="27aaacm7777c1zp")

		self.assertEqual(doc.gst_number, "27AAACM7777C1ZP")

	def test_pan_validation_format(self):
		"""A malformed PAN number is refused at save."""
		with self.assertRaises(frappe.ValidationError):
			make_onboarding(pan_number="AAACM123C")

	def test_minimum_documents_required(self):
		"""A draft saves without documents but cannot be submitted."""
		original = get_settings_value("min_documents_required")
		set_settings_value("min_documents_required", 2)

		try:
			doc = make_onboarding(documents=[])

			# The draft exists — the rule is about submission, not saving,
			# because an application still being assembled must stay saveable.
			self.assertTrue(frappe.db.exists("Vendor Onboarding", doc.name))

			with self.assertRaises(frappe.ValidationError):
				doc.submit()
		finally:
			set_settings_value("min_documents_required", original)

	def test_duplicate_gst_blocked(self):
		"""A GST number held by an application under review blocks another."""
		gst = unique_gst()

		first = make_onboarding(gst_number=gst)
		first.submit()

		second = make_onboarding(gst_number=gst)

		with self.assertRaises(frappe.ValidationError):
			second.submit()

	def test_draft_gst_does_not_block(self):
		"""The same number held only by a draft does not block a submission."""
		gst = unique_gst()

		make_onboarding(gst_number=gst)

		second = make_onboarding(gst_number=gst)
		second.submit()

		self.assertEqual(second.onboarding_status, "Under Review")

	def test_approve_creates_supplier(self):
		"""Approving creates a Supplier carrying the application's details."""
		doc = make_onboarding()
		doc.submit()

		result = approve_onboarding(doc.name)

		self.assertTrue(result["supplier"])

		supplier = frappe.get_doc("Supplier", result["supplier"])

		self.assertEqual(supplier.custom_vendor_category, doc.vendor_category)
		self.assertEqual(supplier.custom_onboarding_reference, doc.name)

		doc.reload()

		self.assertEqual(doc.onboarding_status, "Approved")
		self.assertEqual(doc.linked_supplier, supplier.name)

	def test_approve_is_idempotent(self):
		"""A second approval creates no second Supplier."""
		doc = make_onboarding()
		doc.submit()

		approve_onboarding(doc.name)

		count = frappe.db.count("Supplier", {"custom_onboarding_reference": doc.name})

		# Reaching Approved again must not produce another supplier. The
		# workflow refuses the transition, and the guard on linked_supplier
		# would stop creation even if it did not.
		with self.assertRaises(Exception):
			approve_onboarding(doc.name)

		self.assertEqual(
			frappe.db.count("Supplier", {"custom_onboarding_reference": doc.name}), count
		)

	def test_reject_sets_reason(self):
		"""Rejecting records the reason and creates no Supplier."""
		doc = make_onboarding()
		doc.submit()

		reject_onboarding(doc.name, "Incomplete banking details")

		doc.reload()

		self.assertEqual(doc.onboarding_status, "Rejected")
		self.assertEqual(doc.rejection_reason, "Incomplete banking details")
		self.assertFalse(doc.linked_supplier)

	def test_reject_requires_reason(self):
		"""A rejection with no reason is refused."""
		doc = make_onboarding()
		doc.submit()

		with self.assertRaises(frappe.ValidationError):
			reject_onboarding(doc.name, "   ")

	def test_decision_requires_role(self):
		"""A user holding no deciding role cannot approve or reject."""
		doc = make_onboarding()
		doc.submit()

		frappe.set_user("test_purchase_user@example.com")

		try:
			with self.assertRaises(frappe.PermissionError):
				approve_onboarding(doc.name)

			with self.assertRaises(frappe.PermissionError):
				reject_onboarding(doc.name, "not permitted")
		finally:
			# Restored in a finally block: a test that leaves the session as
			# another user makes every test after it fail for reasons that
			# have nothing to do with what they assert.
			frappe.set_user("Administrator")

