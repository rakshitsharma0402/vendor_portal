# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Create the scorecard variable and criteria in dependency order.

These were fixtures, and could not stay fixtures. Frappe imports fixture
files alphabetically by filename, so supplier_scorecard_criteria.json loaded
before supplier_scorecard_variable.json — and a criteria validates that every
variable its formula references already exists. On a fresh site the install
failed before either record was created.

A patch controls its own ordering, which a fixture cannot.
"""

import frappe

VARIABLE_NAME = "Vendor Portal Rating"
CRITERIA_NAME = "Vendor Portal Rating"
PARAM_NAME = "vendor_portal_rating"


def execute():
	"""Create the scorecard variable, then the criteria that references it.

	Both are guarded on existence, so re-running changes nothing and a site
	that already carries them from the previous fixtures is left alone.
	"""
	_create_variable()
	_create_criteria()

	frappe.db.commit()


def _create_variable():
	"""Create the custom scorecard variable pointing at this app's rating.

	The path is resolved by ERPNext with __import__ on the first segment and
	getattr for the rest, which is why vendor_portal/__init__.py imports the
	scorecard module — getattr alone does not load a submodule.
	"""
	if frappe.db.exists("Supplier Scorecard Variable", VARIABLE_NAME):
		return

	frappe.get_doc(
		{
			"doctype": "Supplier Scorecard Variable",
			"variable_label": VARIABLE_NAME,
			"is_custom": 1,
			"param_name": PARAM_NAME,
			"path": "vendor_portal.scorecard.get_portal_rating",
			"description": "Mean portal rating over the period, out of five",
		}
	).insert(ignore_permissions=True)


def _create_criteria():
	"""Create the criteria scoring on that variable.

	Multiplied by twenty because Scorecard Criteria score out of a hundred
	while portal ratings run one to five: a vendor at 4.0 scores 80.
	"""
	if frappe.db.exists("Supplier Scorecard Criteria", CRITERIA_NAME):
		return

	frappe.get_doc(
		{
			"doctype": "Supplier Scorecard Criteria",
			"criteria_name": CRITERIA_NAME,
			"max_score": 100,
			"formula": f"{{{PARAM_NAME}}} * 20",
			"weight": 100,
		}
	).insert(ignore_permissions=True)

    