import json
from pathlib import Path

from aiops_x_api.modules.plugins.builtins import BUILTIN_MANIFESTS
from aiops_x_plugin_sdk import PluginManifest
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[3]


def test_alembic_has_one_linear_enterprise_head() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["0016_discovery_control_plane"]
    revisions = list(script.walk_revisions(base="base", head="heads"))
    assert len(revisions) == 16
    assert all(len(revision._normalized_down_revisions) <= 1 for revision in revisions)


def test_agent_lifecycle_migration_uses_rendered_constraint_name() -> None:
    migration = (ROOT / "migrations/versions/0013_agent_lifecycle.py").read_text(encoding="utf-8")
    assert 'drop_constraint("uq_edge_agents_tenant_id"' in migration
    assert "edge_agents_tenant_id_asset_id_key" not in migration


def test_audit_chain_migration_scopes_the_append_only_trigger_exception() -> None:
    migration = (ROOT / "migrations/versions/0011_audit_hash_chain.py").read_text(encoding="utf-8")
    disable_at = migration.index("ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_append_only")
    update_at = migration.index("UPDATE audit_logs SET partition_key")
    enable_at = migration.index("ALTER TABLE audit_logs ENABLE TRIGGER audit_logs_append_only")
    constraints_at = migration.index('op.alter_column("audit_logs", "partition_key"')
    assert disable_at < update_at < enable_at < constraints_at


def test_plugin_json_contract_matches_runtime_and_builtins() -> None:
    contract = json.loads(
        (ROOT / "packages/contracts/plugins/v1/plugin-manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    runtime = PluginManifest.model_json_schema()
    assert set(contract["required"]) == set(runtime["required"])
    assert set(contract["properties"]) == set(runtime["properties"])
    validated = [PluginManifest.model_validate(item) for item in BUILTIN_MANIFESTS]
    assert len(validated) == 7
    assert {item.risk_level for item in validated} <= {"R0", "R1"}
