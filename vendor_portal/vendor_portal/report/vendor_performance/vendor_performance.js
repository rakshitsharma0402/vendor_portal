// Copyright (c) 2026, Rakshit Sharma and contributors
// For license information, please see license.txt

frappe.query_reports["Vendor Performance"] = {
	filters: [
		{
			fieldname: "vendor_category",
			label: __("Vendor Category"),
			fieldtype: "Link",
			options: "Vendor Category",
		},
		{
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
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
		{
			fieldname: "minimum_rating",
			label: __("Minimum Rating"),
			fieldtype: "Float",
			description: __("Out of 5"),
		},
	],
};

