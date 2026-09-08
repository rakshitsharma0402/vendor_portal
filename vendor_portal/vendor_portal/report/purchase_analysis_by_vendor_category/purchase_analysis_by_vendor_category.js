// Copyright (c) 2026, Rakshit Sharma and contributors
// For license information, please see license.txt

frappe.query_reports["Purchase Analysis by Vendor Category"] = {
	filters: [
		{
			fieldname: "vendor_category",
			label: __("Vendor Category"),
			fieldtype: "Link",
			options: "Vendor Category",
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
		},
	],
};