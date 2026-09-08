# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Classify suppliers that predate the vendor category field.

A supplier created before this app was installed carries an ERPNext supplier
group and nothing else, so the purchase order rating gate cannot judge it and
both reports omit it. Its group is the closest thing to a classification the
site already holds.

The mapping is hardcoded rather than configurable. It is a one-time judgement
about this migration, not a setting: once the patch has run, changing it would
have no effect, and presenting it as tunable would imply otherwise.
"""

import frappe

# ERPNext supplier group to vendor category. Groups absent from this map are
# left alone and reported — guessing at an unfamiliar grouping would put
# suppliers in categories nobody chose, and the rating thresholds attached to
# those categories then start blocking orders for reasons no one can trace.
GROUP_TO_CATEGORY = {
	"Raw Material": "Raw Materials",
	"Raw Materials": "Raw Materials",
	"Packaging": "Packaging",
	"Services": "IT Services",
	"IT Services": "IT Services",
	"Hardware": "IT Services",
	"Office Supplies": "Office Supplies",
	"Stationery": "Office Supplies",
	"Logistics": "Logistics",
	"Distributor": "Logistics",
	"Local": "Office Supplies",
	"Pharmaceutical": "Raw Materials",
	"Electrical": "IT Services",
}


def execute():
	"""Set a vendor category on suppliers that have a group but no category.

	Suppliers that already carry a category are untouched whatever their
	group: a value someone chose outranks one this patch would infer.
	"""
	suppliers = frappe.db.sql(
		"""
		SELECT name, supplier_group
		FROM `tabSupplier`
		WHERE COALESCE(custom_vendor_category, '') = ''
			AND COALESCE(supplier_group, '') != ''
		""",
		as_dict=True,
	)

	if not suppliers:
		return

	valid_categories = set(frappe.get_all("Vendor Category", pluck="name"))

	updated = 0
	unmapped = {}
	missing_categories = {}

	for supplier in suppliers:
		category = GROUP_TO_CATEGORY.get(supplier.supplier_group)

		if not category:
			# Counted by group rather than logged per supplier: two hundred
			# suppliers in one unmapped group is one fact, not two hundred.
			unmapped[supplier.supplier_group] = unmapped.get(supplier.supplier_group, 0) + 1
			continue

		if category not in valid_categories:
			# The category was renamed or never seeded. Writing the link
			# anyway would leave suppliers pointing at nothing, which is worse
			# than leaving them unclassified.
			missing_categories[category] = missing_categories.get(category, 0) + 1
			continue

		frappe.db.set_value(
			"Supplier",
			supplier.name,
			"custom_vendor_category",
			category,
			update_modified=False,
		)

		updated += 1

	_report(updated, unmapped, missing_categories)

	frappe.db.commit()


def _report(updated: int, unmapped: dict, missing_categories: dict):
	"""Record what the patch did and what it could not do.

	A patch that skips records silently leaves someone to discover the gap
	from a report that looks wrong months later.

	Args:
		updated: How many suppliers were classified.
		unmapped: Supplier group to the number of suppliers left in it.
		missing_categories: Category name to the number of suppliers that
			would have been assigned to it.
	"""
	lines = [f"Classified {updated} suppliers."]

	if unmapped:
		lines.append("\nSupplier groups with no mapping, left uncategorised:")
		lines.extend(f"  {group}: {count} suppliers" for group, count in unmapped.items())

	if missing_categories:
		lines.append("\nMapped categories that do not exist on this site:")
		lines.extend(
			f"  {category}: {count} suppliers" for category, count in missing_categories.items()
		)

	message = "\n".join(lines)

	print(message)

	if unmapped or missing_categories:
		frappe.log_error(
			title="Vendor category backfill left suppliers unclassified",
			message=message,
		)

        