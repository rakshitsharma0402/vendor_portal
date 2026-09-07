// Copyright (c) 2026, Rakshit Sharma and contributors
// For license information, please see license.txt

// Entry point for every desk script this app ships. Frappe's esbuild only
// follows imports from files matching *.bundle.js, so modules are collected
// here rather than registered individually in hooks.py — one asset, one hook
// entry, and each subsequent script adds a line below instead of touching
// hooks.py again.

import "./purchase_order_list";
import "./purchase_invoice";
import "./purchase_order";