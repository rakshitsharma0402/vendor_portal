# Copyright (c) 2026, Rakshit Sharma and Contributors
# See license.txt

# Tests for this doctype live in vendor_portal/tests/test_onboarding.py.
#
# Frappe infers a test file's doctype from its folder and then auto-generates
# test records for every doctype it links to, transitively — a walk that
# reaches Payment Gateway, which no longer exists in v16, and fails before any
# test runs. These tests build their own records, so the generation is not
# wanted; moving the file out of this folder is the only way to opt out.