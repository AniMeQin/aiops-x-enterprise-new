import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "apps/api/src/aiops_x_api/modules"


def test_modules_do_not_import_another_domains_orm_models() -> None:
    violations: list[str] = []
    for source in sorted(MODULES.glob("*/*.py")):
        owner = source.parent.name
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            parts = node.module.split(".")
            if len(parts) < 5 or parts[:2] != ["aiops_x_api", "modules"]:
                continue
            imported_domain = parts[2]
            imports_orm = parts[3:] == ["infrastructure", "models"]
            if imports_orm and imported_domain != owner:
                violations.append(
                    f"{source.relative_to(ROOT)}:{node.lineno} imports {imported_domain} ORM"
                )
    assert violations == []


def test_public_http_routes_are_versioned_except_platform_probes() -> None:
    from aiops_x_api.main import create_app

    allowed = {
        "/health",
        "/ready",
        "/metrics",
        "/docs",
        "/docs/oauth2-redirect",
        "/openapi.json",
    }
    paths = {
        path
        for route in create_app().routes
        if isinstance((path := getattr(route, "path", None)), str)
    }
    assert all(path in allowed or path.startswith("/api/v1/") for path in paths)


def test_openapi_declares_the_standard_sanitized_error_contract() -> None:
    from aiops_x_api.main import create_app

    document = create_app().openapi()
    operation = document["paths"]["/api/v1/monitoring/targets"]["post"]
    for status in ("401", "403", "404", "409", "422", "503"):
        response = operation["responses"][status]
        schema = response["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
