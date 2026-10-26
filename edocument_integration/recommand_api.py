# Copyright (c) 2025, Prilk Consulting BV and contributors
# For license information, please see license.txt

"""
Recommand PEPPOL API Client

This module provides a client for interacting with the Recommand PEPPOL API.
Recommand is an open-source PEPPOL service provider that offers a RESTful API
for sending and receiving PEPPOL documents.

Documentation: https://peppol.recommand.eu/api-reference
GitHub: https://github.com/brbxai/recommand-peppol
"""

import json
from typing import Any

import frappe
import requests
from frappe import _


class RecommandAPIClient:
	"""
	Client for interacting with the Recommand PEPPOL API.

	Recommand provides a RESTful API for PEPPOL document transmission
	with features like document verification, inbox management, and
	transparent pricing.
	"""

	def __init__(self, api_key: str, api_secret: str, base_url: str = "https://peppol.recommand.eu"):
		"""
		Initialize the Recommand API client.

		Args:
			api_key: Recommand API key for authentication
			api_secret: Recommand API secret for authentication
			base_url: Base URL for the Recommand API (default: https://peppol.recommand.eu)
		"""
		self.api_key = api_key
		self.api_secret = api_secret
		self.base_url = base_url.rstrip("/")
		self.session = requests.Session()

		# Use Basic Authentication as per Recommand docs
		import base64

		credentials = f"{api_key}:{api_secret}"
		encoded_credentials = base64.b64encode(credentials.encode()).decode()

		self.session.headers.update(
			{
				"Authorization": f"Basic {encoded_credentials}",
				"Content-Type": "application/json",
				"Accept": "application/json",
			}
		)

	def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
		"""
		Make a request to the Recommand API.

		Args:
			method: HTTP method (GET, POST, etc.)
			endpoint: API endpoint
			**kwargs: Additional arguments for requests

		Returns:
			Response object
		"""
		url = f"{self.base_url}{endpoint}"

		try:
			response = self.session.request(method, url, **kwargs)
			return response
		except requests.exceptions.RequestException as e:
			error_msg = f"Recommand API request failed: {e!s}"
			frappe.log_error(title="Recommand API Error", message=error_msg)
			raise Exception(error_msg)

	# ============================================================================
	# DOCUMENT TRANSMISSION METHODS
	# ============================================================================

	def send_document(self, company_id: str, xml_content: str, document_type: str = "xml") -> dict[str, Any]:
		"""
		Send a PEPPOL document via Recommand.

		Args:
			company_id: Recommand company ID
			xml_content: PEPPOL UBL XML document content
			document_type: Type of document (xml for UBL XML, invoice for structured data)

		Returns:
			Transmission result with document ID and status
		"""
		endpoint = f"/api/peppol/{company_id}/sendDocument"

		# Handle both string and bytes content
		if isinstance(xml_content, bytes):
			xml_content_str = xml_content.decode("utf-8")
		else:
			xml_content_str = xml_content

		# Extract recipient information from XML for Recommand API
		from lxml import etree as ET

		try:
			from edocument.edocument.profiles.peppol import UBL_NAMESPACES

			root = ET.fromstring(
				xml_content_str.encode("utf-8") if isinstance(xml_content_str, str) else xml_content_str
			)

			# Find customer EndpointID using namespace dictionary
			customer_endpoint = root.find(
				".//cac:AccountingCustomerParty/cac:Party/cbc:EndpointID", UBL_NAMESPACES
			)

			if customer_endpoint is not None:
				recipient_id = customer_endpoint.text
				recipient_scheme = customer_endpoint.get("schemeID", "0088")
				# Format: "schemeId:value" as per Recommand API docs
				recipient = f"{recipient_scheme}:{recipient_id}"
			else:
				raise Exception(
					"Recipient EndpointID not found in XML. Please configure electronic address for customer."
				)
		except ET.ParseError as e:
			raise Exception(f"Failed to parse XML to extract recipient: {e!s}")
		except Exception as e:
			raise Exception(f"Failed to extract recipient from XML: {e!s}")

		# Payload for UBL XML upload according to Recommand docs
		# recipient format: "schemeId:value" (e.g., "0208:BE0429026446")
		# doctypeId: PEPPOL document type (e.g., "Invoice" for UBL 2.1 invoices)
		payload = {
			"recipient": recipient,  # Required: PEPPOL recipient in "schemeId:value" format
			"documentType": document_type,  # "xml" for UBL XML
			# "doctypeId": "Invoice",  # PEPPOL document type identifier
			"document": xml_content_str,  # UBL XML as string
		}

		try:
			response = self._make_request("POST", endpoint, json=payload)

			if not response.ok:
				try:
					error_data = response.json()
					error_text = json.dumps(error_data)
				except json.JSONDecodeError:
					error_text = response.text

				error_msg = f"Recommand API error ({response.status_code}): {error_text}"
				frappe.log_error(
					title="Recommand API Error",
					message=f"{error_msg}\nRequest Payload: {json.dumps(payload)}",
				)
				raise Exception(error_msg)

			# Parse response
			result = response.json()
			document_id = result.get("id", "unknown")

			return {"status": "success", "document_id": document_id, "response": result}

		except requests.exceptions.RequestException as e:
			error_msg = f"Recommand document transmission failed: {e!s}"
			frappe.log_error(title="Recommand Transmission Error", message=error_msg)
			raise Exception(error_msg)

	def get_documents(self, team_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
		"""
		List all sent and received documents.

		Args:
			team_id: Recommand team ID
			limit: Number of documents to retrieve
			offset: Offset for pagination

		Returns:
			List of documents
		"""
		endpoint = f"/api/peppol/{team_id}/documents"
		params = {"limit": limit, "offset": offset}

		try:
			response = self._make_request("GET", endpoint, params=params)
			response.raise_for_status()
			return response.json()
		except requests.exceptions.RequestException as e:
			error_msg = f"Recommand get documents failed: {e!s}"
			frappe.log_error(title="Recommand Get Documents Error", message=error_msg)
			raise Exception(error_msg)

	def get_inbox(self, team_id: str, company_id: str | None = None) -> dict[str, Any]:
		"""
		Access unread incoming documents.

		Args:
			team_id: Recommand team ID
			company_id: Optional company ID to filter documents

		Returns:
			List of unread documents
		"""
		endpoint = f"/api/peppol/{team_id}/inbox"
		params = {}
		if company_id:
			params["companyId"] = company_id

		try:
			response = self._make_request("GET", endpoint, params=params)
			response.raise_for_status()
			return response.json()
		except requests.exceptions.RequestException as e:
			error_msg = f"Recommand get inbox failed: {e!s}"
			frappe.log_error(title="Recommand Get Inbox Error", message=error_msg)
			raise Exception(error_msg)

	def verify_recipient(self, recipient_id: str, scheme: str = "GLN") -> dict[str, Any]:
		"""
		Verify if a recipient is registered in the PEPPOL network.

		Args:
			recipient_id: Recipient identifier
			scheme: Identifier scheme (GLN, VAT, etc.)

		Returns:
			Verification result
		"""
		endpoint = "/api/peppol/verify"
		payload = {"recipient_id": recipient_id, "scheme": scheme}

		try:
			response = self._make_request("POST", endpoint, json=payload)
			response.raise_for_status()
			return response.json()
		except requests.exceptions.RequestException as e:
			error_msg = f"Recommand recipient verification failed: {e!s}"
			frappe.log_error(title="Recommand Verification Error", message=error_msg)
			raise Exception(error_msg)

	def get_document_status(self, team_id: str, document_id: str) -> dict[str, Any]:
		"""
		Get the status of a specific document.

		Args:
			team_id: Recommand team ID
			document_id: Document ID

		Returns:
			Document status information
		"""
		endpoint = f"/api/peppol/{team_id}/documents/{document_id}"

		try:
			response = self._make_request("GET", endpoint)
			response.raise_for_status()
			return response.json()
		except requests.exceptions.RequestException as e:
			error_msg = f"Recommand get document status failed: {e!s}"
			frappe.log_error(title="Recommand Document Status Error", message=error_msg)
			raise Exception(error_msg)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def get_recommand_client(integration_settings: dict[str, Any]) -> RecommandAPIClient:
	"""
	Get a Recommand API client from integration settings.

	Args:
		integration_settings: Dictionary containing API key, secret and base URL

	Returns:
		RecommandAPIClient instance
	"""
	api_key = integration_settings.get("api_key")
	api_secret = integration_settings.get("api_secret")
	base_url = integration_settings.get("base_url", "https://peppol.recommand.eu")

	if not api_key:
		raise Exception("Recommand API key not configured")

	if not api_secret:
		raise Exception("Recommand API secret not configured")

	return RecommandAPIClient(api_key, api_secret, base_url)


def transmit_invoice(xml_content: str, invoice_doc=None, integration_settings=None) -> dict[str, Any]:
	"""
	Transmit PEPPOL invoice XML via Recommand API.

	Args:
		xml_content: PEPPOL UBL 2.1 XML invoice content
		invoice_doc: Frappe EDocument document object (optional)
		integration_settings: Recommand integration settings

	Returns:
		Transmission result with document ID and status
	"""
	try:
		# Get Recommand client
		recommand_client = get_recommand_client(integration_settings)

		# Extract company_id from integration settings (stored in company_id field)
		company_id = integration_settings.get("company_id")
		if not company_id:
			raise Exception("Company ID not configured in integration settings (company_id field)")

		# Send document via Recommand
		transmission_result = recommand_client.send_document(
			company_id=company_id,
			xml_content=xml_content,
			document_type="xml",  # Use "xml" for UBL XML upload
		)

		return {
			"status": "success",
			"document_id": transmission_result.get("document_id"),
			"response": transmission_result,
		}

	except Exception as e:
		error_msg = f"Recommand transmission failed: {e!s}"
		frappe.log_error(title="Recommand Transmission Error", message=error_msg)
		raise Exception(error_msg)


def validate_recommand_connection(
	api_key: str, api_secret: str, base_url: str = "https://peppol.recommand.eu"
) -> dict[str, Any]:
	"""
	Validate Recommand API connection.

	Args:
		api_key: Recommand API key
		api_secret: Recommand API secret
		base_url: Recommand API base URL

	Returns:
		Validation result
	"""
	try:
		client = RecommandAPIClient(api_key, api_secret, base_url)

		# Try to make a simple API call to verify connection
		# This could be a health check or a simple endpoint
		response = client._make_request("GET", "/api/health")

		if response.status_code == 200:
			return {"status": "success", "message": "Recommand API connection successful"}
		else:
			return {"status": "error", "message": f"Recommand API connection failed: {response.status_code}"}

	except Exception as e:
		return {"status": "error", "message": f"Recommand API connection failed: {e!s}"}


def poll_inbox(
	integration_settings: dict[str, Any] | None = None, company_id: str | None = None
) -> dict[str, Any]:
	"""
	Poll Recommand inbox for new incoming invoices and return XML content.

	Returns:
		Dictionary with list of XML bytes and metadata
	"""
	client = get_recommand_client(integration_settings)

	# For inbox endpoint, we need team_id (account_id), not company_id
	team_id = integration_settings.get("account_id")
	if not team_id:
		raise Exception("Account ID (team ID) not found in integration settings")

	# Company ID is still needed for document status
	company_id = company_id or integration_settings.get("company_id")
	if not company_id:
		raise Exception("Company ID not found in integration settings")

	# Use team_id for inbox endpoint, optionally filter by company_id
	inbox_result = client.get_inbox(team_id, company_id=company_id)
	documents = inbox_result.get("documents", []) or inbox_result.get("data", []) or []

	if not documents:
		return {"status": "success", "message": "No new invoices found", "invoices": []}

	# Fetch XML content for each document
	invoices = []
	for doc in documents:
		try:
			document_id = doc.get("id")
			# Use team_id for document status endpoint as well
			doc_details = client.get_document_status(team_id, document_id)

			# Extract XML from response structure: {'success': True, 'document': {'xml': '...', ...}}
			document_obj = doc_details.get("document", {})
			if not document_obj:
				frappe.log_error(
					title="Recommand Inbox Polling Error",
					message=f"No 'document' key found in response for {document_id}. Response keys: {list(doc_details.keys())}",
				)
				continue

			xml_content = document_obj.get("xml")
			if not xml_content:
				frappe.log_error(
					title="Recommand Inbox Polling Error",
					message=f"No 'xml' key found in document object for {document_id}. Document keys: {list(document_obj.keys())}",
				)
				continue

			xml_bytes = xml_content.encode("utf-8")
			invoices.append(
				{
					"xml_bytes": xml_bytes,
					"document_id": document_id,
					"metadata": doc,  # Include original document metadata
				}
			)
		except Exception as e:
			frappe.log_error(
				title="Recommand Inbox Polling Error",
				message=f"Failed to fetch document {doc.get('id')}: {e!s}\nTraceback: {frappe.get_traceback()}",
			)

	return {"status": "success", "message": f"Found {len(invoices)} invoice(s)", "invoices": invoices}
