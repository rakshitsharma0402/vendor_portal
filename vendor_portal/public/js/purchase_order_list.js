// Copyright (c) 2026, Rakshit Sharma and contributors
// For license information, please see license.txt

// Extends ERPNext's own Purchase Order list settings rather than replacing
// them. A bare assignment to frappe.listview_settings["Purchase Order"] would
// discard ERPNext's status colours, filters and bulk actions along with
// anything another app has added.

frappe.listview_settings["Purchase Order"] = Object.assign(
	frappe.listview_settings["Purchase Order"] || {},
	{
		add_fields: [
			"supplier",
			"supplier_name",
			"grand_total",
			"per_received",
			"schedule_date",
			"status",
			"docstatus",
		],

		get_indicator: function (doc) {
			// Drafts and cancelled orders are not waiting on a delivery, so
			// ERPNext's own indicator stays. Returning undefined hands the
			// decision back rather than colouring them wrongly.
			if (doc.docstatus !== 1) {
				return;
			}

			if (flt(doc.per_received) >= 100) {
				return [__("Completed"), "green", "per_received,>=,100"];
			}

			// Overdue is a display judgement made from fields already fetched
			// for the list: no extra query, and no server rule to keep in step
			// because nothing here changes data.
			const overdue =
				doc.schedule_date && frappe.datetime.get_day_diff(frappe.datetime.now_date(), doc.schedule_date) > 0;

			if (overdue) {
				return [__("Overdue"), "red", "per_received,<,100"];
			}

			return [__("To Receive"), "orange", "per_received,<,100"];
		},
	}
);