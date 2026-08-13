# Database migrations

Alembic is the only supported mechanism for changing the control-plane schema. The initial migration creates tenant, project, identity, CMDB, and append-only audit foundations. Run `make migrate` against PostgreSQL; never use ORM `create_all` in production.
