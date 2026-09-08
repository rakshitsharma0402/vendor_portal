// Copyright (c) 2026, Rakshit Sharma and contributors
// For license information, please see license.txt

frappe.pages["vendor-analytics"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Vendor Analytics"),
		single_column: true,
	});

	page.main.html(`
		<div class="row">
			<div class="col-sm-6"><div id="vp-rating-distribution"></div></div>
			<div class="col-sm-6"><div id="vp-onboarding-pipeline"></div></div>
		</div>
		<div class="row" style="margin-top: 24px;">
			<div class="col-sm-6"><div id="vp-category-spend"></div></div>
			<div class="col-sm-6"><div id="vp-delivery-trend"></div></div>
		</div>
	`);

	// One request draws the whole page. Four would render it in stages and
	// pay the round trip four times to answer one question.
	frappe.call({
		method: "vendor_portal.api.get_dashboard_data",
		freeze: true,
		freeze_message: __("Loading vendor analytics..."),
		callback: function (response) {
			const data = response.message;

			if (!data) {
				return;
			}

			render_chart(
				"#vp-rating-distribution",
				__("Suppliers by rating"),
				data.rating_distribution,
				"bar",
				__("Suppliers")
			);

			render_chart(
				"#vp-onboarding-pipeline",
				__("Onboarding pipeline"),
				data.onboarding_pipeline,
				"bar",
				__("Applications")
			);

			render_chart(
				"#vp-category-spend",
				__("Purchase value by category"),
				data.category_spend,
				"pie",
				__("Value")
			);

			render_chart(
				"#vp-delivery-trend",
				__("Average delivery score by month"),
				data.delivery_trend,
				"line",
				__("Score")
			);
		},
	});
};

function render_chart(selector, title, dataset, type, series_name) {
	// A chart with no points draws axes around nothing, which reads as a
	// rendering failure. Saying so is clearer.
	if (!dataset || !dataset.labels || !dataset.labels.length) {
		$(selector).html(`
			<h5>${title}</h5>
			<p class="text-muted">${__("Nothing to show yet.")}</p>
		`);

		return;
	}

	new frappe.Chart(selector, {
		title: title,
		type: type,
		height: 260,
		data: {
			labels: dataset.labels,
			datasets: [{ name: series_name, values: dataset.values }],
		},
	});
}

