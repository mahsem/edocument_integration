# Copyright (c) 2025, Prilk Consulting BV and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = ["Company", "EDocument Profile"]

PEPPOL_INVOICE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
	xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
	xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
	<cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0</cbc:CustomizationID>
	<cbc:ProfileID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</cbc:ProfileID>
	<cbc:ID>INV-1</cbc:ID>
	<cbc:IssueDate>2026-10-01</cbc:IssueDate>
	<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
	<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
	<cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="EUR">0</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>"""


class IntegrationTestEDocumentIntegrationSettings(IntegrationTestCase):
	"""
	Integration tests for EDocumentIntegrationSettings.
	Use this class for testing interactions between multiple components.
	"""

	def test_already_imported_document_is_skipped_silently(self):
		reference = "TEST-INBOX-DOC-0001"
		frappe.get_doc({"doctype": "EDocument", "reference": reference, "direction": "Incoming"}).insert(
			ignore_permissions=True
		)

		error_logs_before = frappe.db.count("Error Log")

		result = frappe.new_doc("EDocument Integration Settings").process_incoming_document(
			b"<Invoice/>", reference
		)

		self.assertTrue(result["skipped"])
		self.assertEqual(result["reason"], "duplicate")
		self.assertEqual(
			frappe.db.count("Error Log"),
			error_logs_before,
			"Skipping an already imported document must not write an Error Log",
		)

	def test_incoming_xml_is_attached_once(self):
		reference = "TEST-INBOX-DOC-0002"
		# The import commits; keep it in the test transaction so the class rollback undoes it
		self.enterContext(patch.object(frappe.db, "commit"))

		result = frappe.new_doc("EDocument Integration Settings").process_incoming_document(
			PEPPOL_INVOICE_XML, reference
		)

		attachments = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "EDocument", "attached_to_name": result["edocument"]},
			fields=["file_url", "attached_to_field"],
		)
		self.assertEqual(len(attachments), 1)
		self.assertEqual(attachments[0].attached_to_field, "xml_file")
		self.assertEqual(
			attachments[0].file_url, frappe.db.get_value("EDocument", result["edocument"], "xml_file")
		)
