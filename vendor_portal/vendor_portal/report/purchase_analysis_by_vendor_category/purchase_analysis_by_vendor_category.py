# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Spend and vendor quality aggregated to the category level.

Queried per supplier and folded in Python rather than grouped in SQL. The
"lowest rating supplier" column asks which row held the minimum, which a plain
GROUP BY cannot answer — it needs a window function or a correlated subquery
per category. With a handful of categories the supplier-level result is small
enough to fold in memory, and the code then reads as what it does.
"""

import frappe
from frappe import _
from frappe.utils import flt

from vendor_portal.utils import rating_field_to_scale


def execute(filters: dict | None = None):
	"""Build the category analysis report.

	Args:
		filters: Report filters, all optional.

	Returns:
		A columns, data, message and chart tuple in Frappe's report order.
	"""
	filters = filters or {}

	columns = get_columns()
	data = get_data(filters)
	chart = get_chart(data)

	return columns, data, None, chart


def get_columns() -> list[dict]:
	"""Define the report's columns.

	Returns:
		Column definitions in display order.
	"""
	return [
		{
			"fieldname": "vendor_category",
			"label": _("Vendor Category"),
			"fieldtype": "Link",
			"options": "Vendor Category",
			"width": 160,
		},
		{
			"fieldname": "total_suppliers",
			"label": _("Total Suppliers"),
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"fieldname": "active_suppliers",
			"label": _("Active Suppliers"),
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"fieldname": "total_po_value",
			"label": _("Total PO Value"),
			"fieldtype": "Currency",
			"width": 140,
		},
		{
			"fieldname": "avg_po_value",
			"label": _("Avg PO Value"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "total_items",
			"label": _("Total Items Purchased"),
			"fieldtype": "Float",
			"precision": 2,
			"width": 160,
		},
		{
			"fieldname": "avg_rating",
			"label": _("Avg Vendor Rating"),
			"fieldtype": "Float",
			"precision": 2,
			"width": 140,
		},
		{
			"fieldname": "lowest_rated_supplier",
			"label": _("Lowest Rating Supplier"),
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 180,
		},
	]


def get_data(filters: dict) -> list[dict]:
	"""Aggregate supplier figures up to their categories.

	Args:
		filters: Report filters, all optional.

	Returns:
		One row per category holding at least one supplier, highest spend
		first.
	"""
	suppliers = _get_supplier_figures(filters)

	categories = {}

	for row in suppliers:
		bucket = categories.setdefault(
			row.vendor_category,
			{
				"vendor_category": row.vendor_category,
				"total_suppliers": 0,
				"active_suppliers": 0,
				"total_po_value": 0.0,
				"order_count": 0,
				"total_items": 0.0,
				"ratings": [],
			},
		)

		bucket["total_suppliers"] += 1
		bucket["total_po_value"] += flt(row.po_value)
		bucket["order_count"] += int(row.order_count or 0)
		bucket["total_items"] += flt(row.item_qty)

		# Active means bought from in the period, not ERPNext's disabled flag:
		# a supplier can be perfectly transactable and simply unused.
		if row.order_count:
			bucket["active_suppliers"] += 1

		if row.rating_count:
			bucket["ratings"].append(
				(rating_field_to_scale(row.stored_rating), row.supplier)
			)

	return _shape_rows(categories)


def _get_supplier_figures(filters: dict) -> list[dict]:
	"""Return each categorised supplier with its purchasing figures.

	Order value and line quantity come from separate subqueries. Joining
	`Purchase Order Item` to its parent and summing the parent's total would
	add each order's value once per line it carries.

	Args:
		filters: Report filters.

	Returns:
		One row per supplier that belongs to a category.
	"""
	conditions = ""
	values = {}

	if filters.get("vendor_category"):
		conditions += " AND s.custom_vendor_category = %(vendor_category)s"
		values["vendor_category"] = filters["vendor_category"]

	order_dates = ""

	if filters.get("from_date"):
		order_dates += " AND po.transaction_date >= %(from_date)s"
		values["from_date"] = filters["from_date"]

	if filters.get("to_date"):
		order_dates += " AND po.transaction_date <= %(to_date)s"
		values["to_date"] = filters["to_date"]

	return frappe.db.sql(
		f"""
		SELECT
			s.name AS supplier,
			s.custom_vendor_category AS vendor_category,
			s.custom_vendor_rating AS stored_rating,
			COALESCE(s.custom_total_rating_count, 0) AS rating_count,

			(
				SELECT COUNT(*)
				FROM `tabPurchase Order` po
				WHERE po.supplier = s.name AND po.docstatus = 1 {order_dates}
			) AS order_count,

			(
				SELECT COALESCE(SUM(po.base_grand_total), 0)
				FROM `tabPurchase Order` po
				WHERE po.supplier = s.name AND po.docstatus = 1 {order_dates}
			) AS po_value,

			(
				SELECT COALESCE(SUM(poi.qty), 0)
				FROM `tabPurchase Order Item` poi
				INNER JOIN `tabPurchase Order` po ON po.name = poi.parent
				WHERE po.supplier = s.name AND po.docstatus = 1 {order_dates}
			) AS item_qty

		FROM `tabSupplier` s
		WHERE s.custom_vendor_category IS NOT NULL
			AND s.custom_vendor_category != ''
			{conditions}
		""",
		values,
		as_dict=True,
	)


def _shape_rows(categories: dict) -> list[dict]:
	"""Turn the accumulated buckets into display rows.

	Args:
		categories: Category name to its accumulated figures.

	Returns:
		Rows ordered by spend, highest first.
	"""
	rows = []

	for bucket in categories.values():
		ratings = bucket["ratings"]

		# min() over (rating, supplier) pairs answers which supplier held the
		# lowest score — the part a GROUP BY cannot return.
		lowest = min(ratings)[1] if ratings else None

		rows.append(
			{
				"vendor_category": bucket["vendor_category"],
				"total_suppliers": bucket["total_suppliers"],
				"active_suppliers": bucket["active_suppliers"],
				"total_po_value": bucket["total_po_value"],
				# Divided by orders, not by suppliers: the average order is
				# what a buyer compares against, and averaging per-supplier
				# averages would weight a one-order vendor equally with one
				# that placed fifty.
				"avg_po_value": (bucket["total_po_value"] / bucket["order_count"])
				if bucket["order_count"]
				else 0,
				"total_items": bucket["total_items"],
				"avg_rating": (sum(r for r, _s in ratings) / len(ratings))
				if ratings
				else 0,
				"lowest_rated_supplier": lowest,
			}
		)

	return sorted(rows, key=lambda row: row["total_po_value"], reverse=True)


def get_chart(data: list[dict]) -> dict | None:
	"""Build a pie chart of purchase value by category.

	Args:
		data: The report's shaped rows.

	Returns:
		A chart definition, or None when nothing has been spent.
	"""
	spending = [row for row in data if row["total_po_value"]]

	if not spending:
		return None

	return {
		"data": {
			"labels": [row["vendor_category"] for row in spending],
			"datasets": [
				{
					"name": _("PO Value"),
					"values": [row["total_po_value"] for row in spending],
				}
			],
		},
		"type": "pie",
	}


def execute_snapshot_report(filters: dict | None = None):
	"""Return columns and data for the report.

	This is the main entry point for snapshot report. When 'Synced
	Report' is enabled in report, framework will call this method
	every time the report is refreshed or a filter is updated. It
	accepts the same filters as normal execute. But a utility method -
	get_latest_sync, is also imported.

	"""
	from frappe.database.duckdb.database import get_latest_sync

	columns = get_columns()
	data = get_data()

	return columns, data

