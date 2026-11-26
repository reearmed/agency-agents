"""Static contract checks for the not-yet-deployed Business OS API."""
from pathlib import Path
import unittest

import yaml

from identity_boundary import BUSINESS_OS_ROLES, BUSINESS_OS_SCOPES


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "api" / "openapi.yaml"


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))

    def test_openapi_version_and_placeholder_server_are_explicit(self):
        self.assertEqual(self.spec["openapi"], "3.1.0")
        self.assertIn("example.invalid", self.spec["servers"][0]["url"])
        self.assertIn("No server is deployed", self.spec["info"]["description"])

    def test_mutating_routes_require_bearer_security_and_declared_scopes(self):
        for path, methods in self.spec["paths"].items():
            for method, operation in methods.items():
                if method.lower() not in {"post", "put", "patch", "delete"}:
                    continue
                with self.subTest(path=path, method=method):
                    self.assertTrue(operation.get("security", self.spec.get("security")))
                    self.assertTrue(operation.get("x-required-scopes"))

    def test_approval_and_budget_routes_require_human_roles(self):
        approval = self.spec["paths"]["/approvals/{approval_id}/decision"]["post"]
        budget = self.spec["paths"]["/budgets/{period}"]["put"]
        kill_switch = self.spec["paths"]["/kill-switch"]["post"]
        self.assertIn("business-os:human-approver", approval["x-required-roles"])
        self.assertIn("business-os:budget-operator", budget["x-required-roles"])
        self.assertIn("business-os:operator", kill_switch["x-required-roles"])

    def test_all_api_scope_and_role_extensions_are_allowlisted(self):
        for path, methods in self.spec["paths"].items():
            for method, operation in methods.items():
                if not isinstance(operation, dict):
                    continue
                with self.subTest(path=path, method=method):
                    self.assertTrue(set(operation.get("x-required-scopes", [])) <= BUSINESS_OS_SCOPES)
                    self.assertTrue(set(operation.get("x-required-roles", [])) <= BUSINESS_OS_ROLES)

    def test_no_public_execution_or_adapter_routes_exist(self):
        paths = self.spec["paths"]
        self.assertFalse(any("execute" in path or "adapter" in path for path in paths))

    def test_mutation_request_schemas_reject_unknown_fields(self):
        schemas = self.spec["components"]["schemas"]
        for name in ("TaskProposal", "ArtifactProposal", "ApprovalProposal", "ApprovalDecision", "BudgetLimit"):
            with self.subTest(schema=name):
                self.assertIs(schemas[name]["additionalProperties"], False)

    def test_operation_ids_are_unique(self):
        ids = [
            operation["operationId"]
            for methods in self.spec["paths"].values()
            for operation in methods.values()
            if isinstance(operation, dict) and "operationId" in operation
        ]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
