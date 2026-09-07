// Copyright (c) 2026, Rakshit Sharma and contributors
// For license information, please see license.txt

// frappe.ui.form.on is additive: ERPNext's own refresh handler for Purchase
// Invoice still runs, and so does any other app's. This is the opposite of
// listview_settings, where assignment destroys what was already registered.

// The rating at which a vendor is worth questioning before an invoice is
// approved. Vendor Portal Settings holds a low_rating_threshold, but this
// banner is specified at 3 and reading settings would cost a round trip on
// every form load — the one magic number in this codebase, recorded as such.
const LOW_RATING_THRESHOLD = 3;

// Frappe's Rating field stores a 0-1 fraction. The server converts through
// vendor_portal.utils, which cannot be imported here, so the scale is
// repeated — a known duplication, deliberate rather than overlooked.
const RATING_SCALE_MAX = 5;

frappe.ui.form.on("Purchase Invoice", {
	refresh: function (frm) {
		show_low_rating_warning(frm);
	},

	supplier: function (frm) {
		show_low_rating_warning(frm);
	},
});

function show_low_rating_warning(frm) {
	// Comments accumulate across refreshes, so clear before adding. Without
	// this the banner stacks every time the user saves.
	frm.dashboard.clear_comment();

	if (!frm.doc.supplier) {
		return;
	}

	const supplier = frm.doc.supplier;

	frappe.db
		.get_value("Supplier", supplier, ["custom_vendor_rating", "custom_total_rating_count"])
		.then((response) => {
			const values = response.message;

			if (!values) {
				return;
			}

			// The form may have moved on while the fetch was in flight.
			if (frm.doc.supplier !== supplier) {
				return;
			}

			// No ratings yet is not a bad rating. A new vendor should not be
			// flagged for having no history.
			if (!values.custom_total_rating_count) {
				return;
			}

			const rating = (values.custom_vendor_rating || 0) * RATING_SCALE_MAX;

			if (rating >= LOW_RATING_THRESHOLD) {
				return;
			}

			frm.dashboard.add_comment(
				__(
					"Note: This supplier has a low vendor rating ({0}/5). Consider reviewing vendor performance.",
					[rating.toFixed(1)]
				),
				"orange",
				true
			);
		});
}

