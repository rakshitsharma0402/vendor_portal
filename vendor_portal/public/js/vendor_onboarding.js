// Copyright (c) 2026, Rakshit Sharma and contributors
// For license information, please see license.txt

// Review controls on the Vendor Onboarding form. The workflow's Actions menu
// reaches the same two endpoints, but it is a dropdown a reviewer has to know
// to open, and its Reject action cannot collect a reason — the field has to
// be filled first. These buttons make the reason part of the act. Both routes
// converge on the same endpoints and the same document reaction, so there is
// one code path with two entrances.

// Mirrors GST_PATTERN in vendor_onboarding.py: two digits of state code, a
// ten-character PAN, an entity code, a fixed Z, and a check digit. Duplicated
// because a client-side check that asks the server whether the value is valid
// is not a client-side check. The server remains authoritative — this only
// saves the round trip.
const GST_PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[0-9A-Z]{1}Z[0-9A-Z]{1}$/;

frappe.ui.form.on("Vendor Onboarding", {
	refresh: function (frm) {
		add_decision_buttons(frm);
		show_document_progress(frm);
	},

	vendor_category: function (frm) {
		show_category_threshold(frm);
	},

	onload: function (frm) {
		show_category_threshold(frm);
	},

	validate: function (frm) {
		validate_gst_format(frm);
	},
});

function add_decision_buttons(frm) {
	if (frm.doc.onboarding_status !== "Under Review") {
		return;
	}

	// Convenience only. approve_onboarding and reject_onboarding both check
	// the role themselves, so a user who reaches them another way is refused
	// regardless of what this form chose to draw.
	if (!frappe.user.has_role("Purchase Manager")) {
		return;
	}

	frm.add_custom_button(__("Approve"), () => confirm_approval(frm));
	frm.add_custom_button(__("Reject"), () => prompt_rejection(frm));
}

function confirm_approval(frm) {
	frappe.confirm(
		__("Approve {0} and create a supplier record?", [frm.doc.supplier_name]),
		() => {
			frappe.call({
				method:
					"vendor_portal.vendor_portal.doctype.vendor_onboarding.vendor_onboarding.approve_onboarding",
				args: { onboarding_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Approving application..."),
				callback: function (response) {
					if (!response.message) {
						return;
					}

					frappe.show_alert({
						message: response.message.supplier
							? __("Approved. Supplier {0} created.", [response.message.supplier])
							: __("Approved."),
						indicator: "green",
					});

					frm.reload_doc();
				},
			});
		}
	);
}

function prompt_rejection(frm) {
	frappe.prompt(
		{
			fieldname: "reason",
			label: __("Reason for rejection"),
			fieldtype: "Small Text",
			reqd: 1,
		},
		(values) => {
			frappe.call({
				method:
					"vendor_portal.vendor_portal.doctype.vendor_onboarding.vendor_onboarding.reject_onboarding",
				args: { onboarding_name: frm.doc.name, reason: values.reason },
				freeze: true,
				freeze_message: __("Rejecting application..."),
				callback: function (response) {
					if (!response.message) {
						return;
					}

					frappe.show_alert({
						message: __("Application rejected."),
						indicator: "orange",
					});

					frm.reload_doc();
				},
			});
		},
		__("Reject {0}", [frm.doc.supplier_name]),
		__("Reject")
	);
}

function show_category_threshold(frm) {
	if (!frm.doc.vendor_category) {
		frm.set_df_property("vendor_category", "description", "");
		return;
	}

	const category = frm.doc.vendor_category;

	frappe.db
		.get_value("Vendor Category", category, "minimum_rating_threshold")
		.then((response) => {
			// The reader may have changed category while this resolved.
			if (frm.doc.vendor_category !== category) {
				return;
			}

			const threshold = response.message && response.message.minimum_rating_threshold;

			if (!threshold) {
				return;
			}

			// Shown as the field's own description rather than a message:
			// it belongs where the reader is already looking, and it
			// survives a refresh without being re-added.
			frm.set_df_property(
				"vendor_category",
				"description",
				__("Minimum rating required for this category: {0}/5", [flt(threshold, 1)])
			);
		});
}

function validate_gst_format(frm) {
	if (!frm.doc.gst_number) {
		return;
	}

	const gst = frm.doc.gst_number.trim().toUpperCase();

	if (GST_PATTERN.test(gst)) {
		// Normalised here as well as on the server so the field shows the
		// reader what will actually be stored.
		frm.set_value("gst_number", gst);
		return;
	}

	frappe.validated = false;

	frappe.msgprint({
		title: __("Invalid GST Number"),
		message: __("{0} is not a valid GST number.", [frappe.utils.escape_html(gst)]),
		indicator: "red",
	});
}

function show_document_progress(frm) {
	const documents = frm.doc.documents || [];

	if (!documents.length) {
		frm.dashboard.clear_headline();
		return;
	}

	const verified = documents.filter((row) => row.is_verified).length;

	frm.dashboard.set_headline(
		__("{0} of {1} documents verified", [verified, documents.length])
	);
}

