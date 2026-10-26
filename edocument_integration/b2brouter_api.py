# Copyright (c) 2025, Prilk Consulting BV and contributors
# For license information, please see license.txt

"""
B2B Router API Client for PEPPOL e-invoicing transmission.

This module provides a comprehensive client for interacting with B2B Router's
REST API for transmitting and managing PEPPOL invoices.
"""

import json
from datetime import datetime, timedelta
from typing import Any

import frappe
import requests
from frappe import _


class B2BRouterAPIClient:
	"""B2B Router API client for PEPPOL invoice transmission."""

	def __init__(self, api_key: str, base_url: str = "https://api.b2brouter.net/v1/"):
		"""
		Initialize B2B Router API client.

		Args:
			api_key: B2B Router API key
			base_url: Base URL for B2B Router API
		"""
		self.api_key = api_key
		self.base_url = base_url.rstrip("/")
		self.session = requests.Session()
		self.session.headers.update(
			{"X-B2B-API-Key": api_key, "Accept": "application/json", "User-Agent": "Frappe-EDocument/1.0"}
		)

	def _make_request(
		self, method: str, endpoint: str, data=None, json_data=None, files=None, timeout: int = 30
	) -> dict[str, Any]:
		"""
		Make HTTP request to B2B Router API.

		Args:
			method: HTTP method (GET, POST, PUT, DELETE)
			endpoint: API endpoint (without base URL)
			data: Raw data for POST requests
			json_data: JSON data for requests
			files: File data for multipart requests
			timeout: Request timeout in seconds

		Returns:
			API response as dictionary

		Raises:
			Exception: For API errors or network issues
		"""
		url = f"{self.base_url}{endpoint}"

		try:
			headers = {}
			if json_data and not files:
				headers["Content-Type"] = "application/json"
				data = json.dumps(json_data)

			response = self.session.request(
				method=method.upper(), url=url, data=data, headers=headers, files=files, timeout=timeout
			)

			response.raise_for_status()

			# Handle empty responses
			if response.content:
				return response.json()
			else:
				return {"success": True}

		except requests.exceptions.RequestException as e:
			error_msg = f"B2B Router API request failed: {e!s}"
			frappe.log_error(title="B2B Router API Error", message=error_msg)
			raise Exception(error_msg)

	# ============================================================================
	# INVOICE TRANSMISSION METHODS
	# ============================================================================

	def create_invoice(self, xml_content: str, invoice_doc=None, integration_settings=None) -> dict[str, Any]:
		"""
		Create/upload invoice to B2B Router.

		Args:
			xml_content: PEPPOL UBL 2.1 XML invoice content
			invoice_doc: Frappe EDocument document object (optional)
			integration_settings: Integration settings with account_id

		Returns:
			Creation result with invoice ID
		"""
		# Use account_id from integration settings
		if integration_settings and integration_settings.get("account_id"):
			account_id = integration_settings.get("account_id")

		# Use the Import endpoint for XML invoices
		create_url = f"{self.base_url}/projects/{account_id}/invoices/import.json"
		create_headers = {"X-B2B-API-Key": self.api_key, "Content-Type": "application/octet-stream"}

		# Encode XML as base64 for import
		import base64

		# Handle both string and bytes input
		if isinstance(xml_content, bytes):
			xml_bytes = xml_content
		else:
			xml_bytes = xml_content.encode("utf-8")

		xml_base64 = base64.b64encode(xml_bytes).decode("utf-8")
		xml_data = f"data:text/xml;name=Invoice.xml;base64,{xml_base64}"

		try:
			response = self.session.post(create_url, data=xml_data, headers=create_headers, timeout=60)

			# Handle 422 errors with detailed error messages
			if response.status_code == 422:
				try:
					error_data = response.json()
					error_messages = error_data.get("errors", [])
					error_msg = f"B2B Router validation failed: {'; '.join(error_messages)}"
					frappe.log_error(title="B2B Router Validation Error", message=error_msg)
					raise Exception(error_msg)
				except Exception:
					raise Exception(f"B2B Router validation failed (422): {response.text}")

			response.raise_for_status()

			# Extract invoice ID from response
			invoice_id = "unknown"
			try:
				if response.headers.get("content-type", "").startswith("application/xml"):
					# Parse XML response to get invoice ID
					import xml.etree.ElementTree as ET

					root = ET.fromstring(response.text)
					invoice_id = root.find(".//id").text if root.find(".//id") is not None else "unknown"
				else:
					# Try JSON response - check for nested invoice object
					result = response.json()
					if "invoice" in result and "id" in result["invoice"]:
						invoice_id = result["invoice"]["id"]
					else:
						invoice_id = result.get("id", "unknown")
			except Exception:
				# If parsing fails, use unknown
				pass

			return {"status": "success", "invoice_id": invoice_id, "response": response.text}

		except requests.exceptions.RequestException as e:
			error_msg = f"B2B Router invoice creation failed: {e!s}"
			frappe.log_error(title="B2B Router Creation Error", message=error_msg)
			raise Exception(error_msg)

	def send_invoice(self, invoice_id: str) -> dict[str, Any]:
		"""
		Send created invoice via B2B Router.

		Args:
			invoice_id: ID of the created invoice

		Returns:
			Send result with transmission information
		"""
		send_url = f"{self.base_url}/invoices/send_invoice/{invoice_id}"
		headers = {"accept": "application/xml", "X-B2B-API-Key": self.api_key}

		try:
			response = self.session.post(send_url, headers=headers, timeout=60)
			response.raise_for_status()

			# Handle response (XML or JSON)
			if response.headers.get("content-type", "").startswith("application/xml"):
				result = {"status": "success", "response": response.text}
			else:
				try:
					result = response.json()
				except Exception:
					result = {"status": "success", "response": response.text}

			return result

		except requests.exceptions.RequestException as e:
			error_msg = f"B2B Router invoice send failed: {e!s}"
			frappe.log_error(title="B2B Router Send Error", message=error_msg)
			raise Exception(error_msg)

	def transmit_invoice(
		self,
		xml_content: str,
		invoice_doc=None,
		integration_settings=None,
		metadata: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		"""
		Transmit PEPPOL invoice XML to B2B Router using create + send workflow.

		Args:
			xml_content: PEPPOL UBL 2.1 XML invoice content
			invoice_doc: Frappe EDocument document object (optional)
			integration_settings: Integration settings with account_id
			metadata: Optional metadata about the invoice

		Returns:
			Transmission result with tracking information
		"""
		try:
			# Step 1: Create/upload the invoice
			create_result = self.create_invoice(xml_content, invoice_doc, integration_settings)

			if create_result["status"] != "success":
				raise Exception(f"Failed to create invoice: {create_result}")

			invoice_id = create_result.get("invoice_id", "unknown")

			# Step 2: Send the created invoice
			send_result = self.send_invoice(invoice_id)

			if send_result["status"] != "success":
				raise Exception(f"Failed to send invoice: {send_result}")

			# Combine results
			result = {
				"status": "success",
				"invoice_id": invoice_id,
				"create_result": create_result,
				"send_result": send_result,
			}

			# Log successful transmission
			frappe.logger().info(f"B2B Router transmission successful: {result}")

			return result

		except Exception as e:
			error_msg = f"B2B Router invoice transmission failed: {e!s}"
			frappe.log_error(title="B2B Router Transmission Error", message=error_msg)
			raise Exception(error_msg)

	def get_invoice_status(self, transmission_id: str) -> dict[str, Any]:
		"""
		Get status of transmitted invoice.

		Args:
			transmission_id: B2B Router transmission ID

		Returns:
			Invoice status information
		"""
		return self._make_request("GET", f"/invoices/{transmission_id}")

	def get_invoice_history(self, transmission_id: str) -> dict[str, Any]:
		"""
		Get detailed history of invoice transmission.

		Args:
			transmission_id: B2B Router transmission ID

		Returns:
			Invoice transmission history
		"""
		return self._make_request("GET", f"/invoices/{transmission_id}/history")

	def cancel_invoice(self, transmission_id: str, reason: str = "") -> dict[str, Any]:
		"""
		Cancel a pending invoice transmission.

		Args:
			transmission_id: B2B Router transmission ID
			reason: Reason for cancellation

		Returns:
			Cancellation result
		"""
		data = {"reason": reason} if reason else {}
		return self._make_request("DELETE", f"/invoices/{transmission_id}", json_data=data)

	# ============================================================================
	# BULK OPERATIONS
	# ============================================================================

	def transmit_invoices_bulk(
		self, xml_files: list[str], metadata: dict[str, Any] | None = None
	) -> dict[str, Any]:
		"""
		Transmit multiple invoices in bulk.

		Args:
			xml_files: List of XML file paths or content strings
			metadata: Optional metadata for the bulk transmission

		Returns:
			Bulk transmission result
		"""
		files = []
		for i, xml in enumerate(xml_files):
			if isinstance(xml, str) and xml.startswith("<?xml"):
				# XML content as string
				files.append(("invoices", (f"invoice_{i}.xml", xml, "application/xml")))
			else:
				# File path
				with open(xml, "rb") as f:
					files.append(("invoices", (f.name, f.read(), "application/xml")))

		return self._make_request("POST", "/invoices/bulk", files=files)

	def get_bulk_status(self, bulk_id: str) -> dict[str, Any]:
		"""
		Get status of bulk transmission.

		Args:
			bulk_id: Bulk transmission ID

		Returns:
			Bulk transmission status
		"""
		return self._make_request("GET", f"/bulk/{bulk_id}")

	# ============================================================================
	# ACCOUNT MANAGEMENT
	# ============================================================================

	def get_account_info(self) -> dict[str, Any]:
		"""
		Get account information and settings.

		Returns:
			Account details including limits and settings
		"""
		return self._make_request("GET", "/account")

	def update_account_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
		"""
		Update account settings.

		Args:
			settings: Settings to update

		Returns:
			Updated account settings
		"""
		return self._make_request("PUT", "/account", json_data=settings)

	# ============================================================================
	# CONTACTS AND PARTNERS
	# ============================================================================

	def get_contacts(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
		"""
		Get list of trading partners/contacts.

		Args:
			filters: Optional filters for contacts

		Returns:
			List of contacts
		"""
		params = filters or {}
		return self._make_request("GET", "/contacts", json_data=params)

	def create_contact(self, contact_data: dict[str, Any]) -> dict[str, Any]:
		"""
		Create a new trading partner contact.

		Args:
			contact_data: Contact information

		Returns:
			Created contact details
		"""
		return self._make_request("POST", "/contacts", json_data=contact_data)

	def update_contact(self, contact_id: str, contact_data: dict[str, Any]) -> dict[str, Any]:
		"""
		Update trading partner contact.

		Args:
			contact_id: Contact ID
			contact_data: Updated contact information

		Returns:
			Updated contact details
		"""
		return self._make_request("PUT", f"/contacts/{contact_id}", json_data=contact_data)

	# ============================================================================
	# REPORTING AND ANALYTICS
	# ============================================================================

	def get_transmission_report(
		self, date_from: str, date_to: str, filters: dict[str, Any] | None = None
	) -> dict[str, Any]:
		"""
		Get transmission report for date range.

		Args:
			date_from: Start date (YYYY-MM-DD)
			date_to: End date (YYYY-MM-DD)
			filters: Optional filters

		Returns:
			Transmission report data
		"""
		params = {"date_from": date_from, "date_to": date_to}
		if filters:
			params.update(filters)

		return self._make_request("GET", "/reports/transmissions", json_data=params)

	def get_invoice_list(
		self, page: int = 1, limit: int = 50, filters: dict[str, Any] | None = None
	) -> dict[str, Any]:
		"""
		Get paginated list of transmitted invoices.

		Args:
			page: Page number
			limit: Items per page
			filters: Optional filters

		Returns:
			Paginated invoice list
		"""
		params = {"page": page, "limit": limit}
		if filters:
			params.update(filters)

		return self._make_request("GET", "/invoices", json_data=params)

	# ============================================================================
	# SYSTEM STATUS AND HEALTH
	# ============================================================================

	def get_system_status(self) -> dict[str, Any]:
		"""
		Get B2B Router system status and health information.

		Returns:
			System status information
		"""
		return self._make_request("GET", "/status")

	def get_rate_limits(self) -> dict[str, Any]:
		"""
		Get current API rate limits and usage.

		Returns:
			Rate limit information
		"""
		return self._make_request("GET", "/rate-limits")

	# ============================================================================
	# WEBHOOK MANAGEMENT
	# ============================================================================

	def register_webhook(self, webhook_data: dict[str, Any]) -> dict[str, Any]:
		"""
		Register a webhook for transmission status updates.

		Args:
			webhook_data: Webhook configuration

		Returns:
			Webhook registration result
		"""
		return self._make_request("POST", "/webhooks", json_data=webhook_data)

	def get_webhooks(self) -> dict[str, Any]:
		"""
		Get list of registered webhooks.

		Returns:
			List of webhooks
		"""
		return self._make_request("GET", "/webhooks")

	def delete_webhook(self, webhook_id: str) -> dict[str, Any]:
		"""
		Delete a webhook.

		Args:
			webhook_id: Webhook ID to delete

		Returns:
			Deletion result
		"""
		return self._make_request("DELETE", f"/webhooks/{webhook_id}")


def get_default_transmission_options() -> dict[str, Any]:
	"""
	Get default transmission options from site config.

	Returns:
		Dictionary with default transmission options
	"""
	options = {}

	# Get priority from site config (default: normal)
	priority = frappe.conf.get("b2b_router_default_priority", "normal")
	if priority and priority.lower() != "normal":
		options["priority"] = priority

	# Get test mode from site config (default: False)
	test_mode = frappe.conf.get("b2b_router_test_mode", False)
	if test_mode:
		options["test_mode"] = True

	# Get timeout from site config (default: 60 seconds)
	timeout = frappe.conf.get("b2b_router_timeout", 60)
	if timeout != 60:
		options["timeout"] = timeout

	return options


def get_b2b_router_client() -> B2BRouterAPIClient:
	"""
	Get B2B Router client from site config settings.

	Returns:
		B2BRouterAPIClient instance
	"""
	api_key = frappe.conf.get("b2b_router_api_key")
	base_url = frappe.conf.get("b2b_router_base_url", "https://api.b2brouter.net/v1/")

	if not api_key:
		raise Exception("B2B Router API key not configured in site config")

	return B2BRouterAPIClient(api_key, base_url)


def validate_api_connection(api_key: str | None = None, base_url: str | None = None) -> dict[str, Any]:
	"""
	Validate B2B Router API connection and credentials.

	Args:
		api_key: B2B Router API key (if None, uses site config)
		base_url: B2B Router base URL (if None, uses default)

	Returns:
		Connection validation result
	"""
	try:
		if api_key and base_url:
			client = B2BRouterAPIClient(api_key, base_url)
		else:
			client = get_b2b_router_client()
		status = client.get_system_status()
		return {
			"status": "success",
			"message": "B2B Router API connection successful",
			"system_status": status,
		}
	except Exception as e:
		return {"status": "error", "message": f"B2B Router API connection failed: {e!s}"}


def poll_inbox(
	integration_settings: dict[str, Any] | None = None, account_id: str | None = None
) -> dict[str, Any]:
	"""Poll B2B Router inbox for new incoming invoices and return XML content."""
	if not integration_settings:
		raise Exception("Integration settings not provided")

	api_key = integration_settings.get("api_key")

	if not api_key:
		raise Exception("API key not found in integration settings")

	# B2B Router inbox polling - placeholder implementation
	return {"status": "success", "message": "No inbox polling implemented for B2B Router yet", "invoices": []}
