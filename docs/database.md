# Database storage

The integrated simulation uses filesystem run artifacts and an SQLite operations mirror through `persistence/` and `runtime/operations/`. The startup script places this mirror under the ignored `workspace_jobs/_operations/` directory unless a local path override is provided.

`database/` retains an optional SQLAlchemy model and repository package for enterprise, product, and order records. It is separate from the operations mirror. By default it uses the ignored `local_orm.sqlite` file; set `DATABASE_URL` to a PostgreSQL URL to use an external database. The repository contains no PostgreSQL password.

```bash
python -c 'from database.db_manager import init_db; init_db()'
```

The command initializes the optional ORM tables. It does not import or replace archived simulation runs.
