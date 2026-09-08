# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Record builders shared across the test suite.

Tests run against a database that is rebuilt per session, so nothing a
developer left on their own site exists here. Every test constructs what it
needs, and the constructing lives in one place rather than three — the
purchase order builder alone needs a company, an item and a warehouse before
it can assert anything about a two-line rule.
"""

import frappe
from frappe.utils import add_days, today

# GST numbers must be unique across live applications, so a suite that reused
# one would see the duplicate check fire in tests that are not about it. The
# counter varies the entity code position, which the pattern accepts freely.
_gst_counter = {"value": 0}


def unique_gst() -> str:
	"""Return a structurally valid GST number unused by earlier calls.

	Returns:
		A 15-character GST number matching the validation pattern.
	"""
	_gst_counter["value"] += 1

	# Two-digit state, five letters, four digits, one letter, entity code,
	# fixed Z, check digit.
	entity = str(_gst_counter["value"] % 10)

	return f"27AAACM{1000 + _gst_counter['value']}C{entity}ZP"


def make_onboarding(**overrides) -> "frappe.Document":
	"""Create a Vendor Onboarding application with valid defaults.

	Args:
		**overrides: Field values replacing the defaults, and `documents` to
			replace the two rows attached by default.

	Returns:
		The inserted, unsubmitted application.
	"""
	documents = overrides.pop(
		"documents",
		[
			{"document_type": "GST Certificate", "document_file": "/files/test.pdf"},
			{"document_type": "PAN Card", "document_file": "/files/test.pdf"},
		],
	)

	values = {
		"doctype": "Vendor Onboarding",
		"supplier_name": "Test Applicant",
		"company_name": "Test Applicant Ltd",
		"email": "applicant@example.com",
		"phone": "9999900000",
		"vendor_category": "Raw Materials",
		"gst_number": unique_gst(),
		"pan_number": "AAACM1234C",
		"address_line_1": "1 Test Road",
		"city": "Pune",
		"state": "Maharashtra",
		"documents": documents,
	}

	values.update(overrides)

	doc = frappe.get_doc(values)
	doc.insert(ignore_permissions=True)

	return doc


def make_supplier(**overrides) -> "frappe.Document":
	"""Create a Supplier with the portal's custom fields set.

	Args:
		**overrides: Field values replacing the defaults.

	Returns:
		The inserted Supplier.
	"""
	values = {
		"doctype": "Supplier",
		"supplier_name": f"Test Supplier {frappe.generate_hash(length=6)}",
		"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
		"custom_vendor_category": "Raw Materials",
	}

	values.update(overrides)

	doc = frappe.get_doc(values)
	doc.insert(ignore_permissions=True)

	return doc


def get_settings_value(fieldname: str):
	"""Read one Vendor Portal Settings value.

	Args:
		fieldname: The setting to read.

	Returns:
		Its current value.
	"""
	return frappe.db.get_single_value("Vendor Portal Settings", fieldname)


def set_settings_value(fieldname: str, value):
	"""Write one Vendor Portal Settings value without running validation.

	Written directly rather than through the document because the settings
	validate their weights as a set: a test adjusting one threshold should not
	have to satisfy rules about a different field.

	Args:
		fieldname: The setting to write.
		value: Its new value.
	"""
	frappe.db.set_single_value("Vendor Portal Settings", fieldname, value)


def make_test_user(email: str, roles: list[str]) -> str:
	"""Create or reuse a user holding the given roles.

	Args:
		email: The user's address.
		roles: Role names to grant.

	Returns:
		The user's name.
	"""
	if frappe.db.exists("User", email):
		return email

	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"roles": [{"role": role} for role in roles],
		}
	)

	user.insert(ignore_permissions=True)

	return user.name

def before_tests():
	"""Prepare the shared state every test session needs.

	A Purchase Order cannot be created without a company, and ERPNext's own
	suites run the setup wizard for the same reason. The roles arrive with the
	app's fixtures; the users holding them do not.
	"""
	frappe.clear_cache()

	if not frappe.db.a_row_exists("Company"):
		from erpnext.setup.utils import before_tests as erpnext_before_tests

		erpnext_before_tests()

	make_test_user("test_vendor_mgr@example.com", ["Vendor Manager"])
	make_test_user("test_purchase_user@example.com", ["Purchase User", "Purchase Team"])

	frappe.db.commit()