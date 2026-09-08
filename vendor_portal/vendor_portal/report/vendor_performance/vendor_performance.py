# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Per-supplier view of ordering volume, delivery reliability and rating.

The joins here need care. A supplier's orders, receipts and ratings are three
independent one-to-many relationships, so joining all of them produces a row
per combination and every SUM across that result is multiplied by the row
counts of the others. Order and receipt figures therefore come from correlated
subqueries, and only the ratings — which the report groups by anyway — are
joined directly.
"""

import frappe
from frappe import _
from frappe.utils import flt

from vendor_portal.utils import rating_field_to_scale

# Delivery scores that mean the goods arrived when promised. VP-1.5 assigns 5
# for on time and complete, 4 for on time but short; 3 and 2 are the late
# equivalents. Deriving the report's timeliness columns from the score rather
# than recomputing dates keeps one definition of "late" in the codebase.
ON_TIME_SCORES = (4, 5)
SHORT_DELIVERY_SCORES = (2, 4)

CHART_SUPPLIER_LIMIT = 10


def execute(filters: dict | None = None):
	"""Build the vendor performance report.

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
			"fieldname": "supplier",
			"label": _("Supplier"),
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 180,
		},
		{
			"fieldname": "vendor_category",
			"label": _("Vendor Category"),
			"fieldtype": "Link",
			"options": "Vendor Category",
			"width": 130,
		},
		{"fieldname": "total_pos", "label": _("Total POs"), "fieldtype": "Int", "width": 90},
		{
			"fieldname": "total_po_value",
			"label": _("Total PO Value"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "total_receipts",
			"label": _("Total Receipts"),
			"fieldtype": "Int",
			"width": 110,
		},
		{
			"fieldname": "avg_delivery",
			"label": _("Avg Delivery"),
			"fieldtype": "Float",
			"precision": 2,
			"width": 110,
		},
		{
			"fieldname": "avg_quality",
			"label": _("Avg Quality"),
			"fieldtype": "Float",
			"precision": 2,
			"width": 110,
		},
		{
			"fieldname": "avg_pricing",
			"label": _("Avg Pricing"),
			"fieldtype": "Float",
			"precision": 2,
			"width": 110,
		},
		{
			"fieldname": "overall_rating",
			"label": _("Overall Rating"),
			"fieldtype": "Float",
			"precision": 2,
			"width": 120,
		},
		{
			"fieldname": "on_time_pct",
			"label": _("On-Time Delivery %"),
			"fieldtype": "Percent",
			"width": 140,
		},
		{
			"fieldname": "short_deliveries",
			"label": _("Short Deliveries"),
			"fieldtype": "Int",
			"width": 120,
		},
	]


def get_data(filters: dict) -> list[dict]:
	"""Run the report query and shape its rows.

	Args:
		filters: Report filters, all optional.

	Returns:
		One row per supplier with purchase history, ordered by rating.
	"""
	conditions, values = _build_conditions(filters)

	rows = frappe.db.sql(
		f"""
		SELECT
			s.name AS supplier,
			s.custom_vendor_category AS vendor_category,

			-- Correlated rather than joined: joining orders and receipts to
			-- the same supplier row would return their cross product, and the
			-- value below would be added once per receipt.
			(
				SELECT COUNT(*)
				FROM `tabPurchase Order` po
				WHERE po.supplier = s.name
					AND po.docstatus = 1
					{{order_dates}}
			) AS total_pos,

			(
				SELECT COALESCE(SUM(po.base_grand_total), 0)
				FROM `tabPurchase Order` po
				WHERE po.supplier = s.name
					AND po.docstatus = 1
					{{order_dates}}
			) AS total_po_value,

			(
				SELECT COUNT(*)
				FROM `tabPurchase Receipt` pr
				WHERE pr.supplier = s.name
					AND pr.docstatus = 1
					{{receipt_dates}}
			) AS total_receipts,

			AVG(CASE WHEN vrl.rating_type = 'Delivery' THEN vrl.score END) AS avg_delivery,
			AVG(CASE WHEN vrl.rating_type = 'Quality' THEN vrl.score END) AS avg_quality,
			AVG(CASE WHEN vrl.rating_type = 'Pricing' THEN vrl.score END) AS avg_pricing,

			s.custom_vendor_rating AS stored_rating,

			SUM(
				CASE WHEN vrl.rating_type = 'Delivery' AND vrl.score IN %(on_time)s
				THEN 1 ELSE 0 END
			) AS on_time_count,

			SUM(
				CASE WHEN vrl.rating_type = 'Delivery'
				THEN 1 ELSE 0 END
			) AS delivery_count,

			SUM(
				CASE WHEN vrl.rating_type = 'Delivery' AND vrl.score IN %(short)s
				THEN 1 ELSE 0 END
			) AS short_deliveries

		FROM `tabSupplier` s
		LEFT JOIN `tabVendor Rating Log` vrl ON vrl.supplier = s.name
		WHERE COALESCE(s.disabled, 0) = 0
			{conditions}
			AND EXISTS (
				SELECT 1 FROM `tabPurchase Order` po
				WHERE po.supplier = s.name AND po.docstatus = 1
			)
		GROUP BY s.name, s.custom_vendor_category, s.custom_vendor_rating
		ORDER BY s.custom_vendor_rating DESC, s.name ASC
		""".format(
			order_dates=_date_clause(filters, "po.transaction_date"),
			receipt_dates=_date_clause(filters, "pr.posting_date"),
		),
		{
			**values,
			"on_time": ON_TIME_SCORES,
			"short": SHORT_DELIVERY_SCORES,
		},
		as_dict=True,
	)

	return _shape_rows(rows, filters)


def _date_clause(filters: dict, field: str) -> str:
	"""Return a date restriction for a subquery, or nothing.

	The field name is chosen by this module, never by the caller, so it is
	safe to interpolate; the dates themselves are bound as parameters.

	Args:
		filters: Report filters.
		field: The qualified column to bound.

	Returns:
		A SQL fragment, empty when neither date is set.
	"""
	clause = ""

	if filters.get("from_date"):
		clause += f" AND {field} >= %(from_date)s"

	if filters.get("to_date"):
		clause += f" AND {field} <= %(to_date)s"

	return clause


def _build_conditions(filters: dict) -> tuple[str, dict]:
	"""Translate the supplier-level filters into SQL.

	An unset filter widens the report rather than excluding everything, so a
	report opened with nothing chosen shows the whole picture.

	Args:
		filters: Report filters.

	Returns:
		The WHERE fragment and the values to bind.
	"""
	conditions = ""
	values = {}

	if filters.get("supplier"):
		conditions += " AND s.name = %(supplier)s"
		values["supplier"] = filters["supplier"]

	if filters.get("vendor_category"):
		conditions += " AND s.custom_vendor_category = %(vendor_category)s"
		values["vendor_category"] = filters["vendor_category"]

	if filters.get("from_date"):
		values["from_date"] = filters["from_date"]

	if filters.get("to_date"):
		values["to_date"] = filters["to_date"]

	return conditions, values


def _shape_rows(rows: list[dict], filters: dict) -> list[dict]:
	"""Convert stored ratings to the 1-5 scale and derive the timeliness columns.

	The minimum rating filter is applied here rather than in SQL because the
	stored value is a 0-1 fraction while the filter is expressed out of five —
	converting once in Python is clearer than dividing the threshold in the
	query and easier to read back.

	Args:
		rows: Raw query rows.
		filters: Report filters.

	Returns:
		Display-ready rows.
	"""
	minimum = flt(filters.get("minimum_rating"))
	shaped = []

	for row in rows:
		overall = rating_field_to_scale(row.stored_rating)

		if minimum and overall < minimum:
			continue

		delivery_count = flt(row.delivery_count)

		shaped.append(
			{
				"supplier": row.supplier,
				"vendor_category": row.vendor_category,
				"total_pos": int(row.total_pos or 0),
				"total_po_value": flt(row.total_po_value),
				"total_receipts": int(row.total_receipts or 0),
				"avg_delivery": flt(row.avg_delivery),
				"avg_quality": flt(row.avg_quality),
				"avg_pricing": flt(row.avg_pricing),
				"overall_rating": overall,
				# Zero rather than null when nothing has been rated: a vendor
				# with no rated deliveries has no percentage, and showing 0%
				# is less misleading than a blank that reads as pending.
				"on_time_pct": (flt(row.on_time_count) / delivery_count * 100)
				if delivery_count
				else 0,
				"short_deliveries": int(row.short_deliveries or 0),
			}
		)

	return shaped


def get_chart(data: list[dict]) -> dict | None:
	"""Build a bar chart of the best-rated suppliers in the result.

	Args:
		data: The report's shaped rows.

	Returns:
		A chart definition, or None when there is nothing to plot.
	"""
	if not data:
		return None

	top = sorted(data, key=lambda row: row["overall_rating"], reverse=True)[
		:CHART_SUPPLIER_LIMIT
	]

	return {
		"data": {
			"labels": [row["supplier"] for row in top],
			"datasets": [
				{
					"name": _("Overall Rating"),
					"values": [row["overall_rating"] for row in top],
				}
			],
		},
		"type": "bar",
		"colors": ["#4CAF50"],
	}

def execute_snapshot_report(filters: dict | None = None):
	"""Entry point when the report is run against a synced snapshot.

	Frappe calls this instead of execute() when Synced Report is enabled on
	the Report record. The report is not synced, so this delegates rather than
	duplicating the query — the option can be turned on later without a code
	change.

	Args:
		filters: Report filters, all optional.

	Returns:
		The same tuple execute() returns.
	"""
	return execute(filters)

