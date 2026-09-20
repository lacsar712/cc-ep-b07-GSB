import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cqrs import DomainError, complete_run, list_runs, start_run
from app.database import Base

# 与 seed.py 一致的提交哈希
SHA_RUN1 = "a1b2c3d4e5f6789012345678abcdef0123456789"
SHA_RUN2 = "f0e1d2c3b4a5968778695a4b3c2d1e0f98765432"
SHA_RUN3 = "9abc8def7a6543210fedcba9876543210abcdef0"


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # JSONB not available on SQLite — compile as JSON (same shim as test_state_machine)
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(_type, compiler, **kw):
        return "JSON"

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def seeded(db):
    r1 = start_run(
        db,
        actor="researcher",
        project="protein-folding",
        name="run1",
        dataset_content_sha256=sha("ds1"),
        code_commit_sha=SHA_RUN1,
        description=None,
        run_id=uuid4(),
    )
    complete_run(db, run_id=r1.id, actor="researcher", result_summary="ok", expected_version=1)

    r2 = start_run(
        db,
        actor="researcher",
        project="drug-screen",
        name="run2",
        dataset_content_sha256=sha("ds2"),
        code_commit_sha=SHA_RUN2,
        description=None,
        run_id=uuid4(),
    )
    complete_run(db, run_id=r2.id, actor="researcher", result_summary="ok", expected_version=1)

    start_run(
        db,
        actor="researcher",
        project="protein-folding",
        name="run3",
        dataset_content_sha256=sha("ds3"),
        code_commit_sha=SHA_RUN3,
        description=None,
        run_id=uuid4(),
    )
    return db


def names(runs):
    return sorted(r.name for r in runs)


def test_no_filter_returns_all(seeded):
    assert names(list_runs(seeded)) == ["run1", "run2", "run3"]


def test_prefix_matches_only_prefix_hits(seeded):
    runs = list_runs(seeded, commit_sha="a1b2", commit_sha_mode="prefix")
    assert names(runs) == ["run1"]


def test_exact_with_partial_sha_returns_empty_not_full_table(seeded):
    runs = list_runs(seeded, commit_sha="a1b2", commit_sha_mode="exact")
    assert runs == []


def test_exact_with_full_sha(seeded):
    runs = list_runs(seeded, commit_sha=SHA_RUN2, commit_sha_mode="exact")
    assert names(runs) == ["run2"]


def test_matching_is_case_insensitive(seeded):
    assert names(list_runs(seeded, commit_sha="A1B2C3D4", commit_sha_mode="prefix")) == ["run1"]
    assert names(list_runs(seeded, commit_sha=SHA_RUN3.upper(), commit_sha_mode="exact")) == ["run3"]


def test_combines_with_project_and_status(seeded):
    assert names(
        list_runs(seeded, project="protein-folding", commit_sha="a1b2", commit_sha_mode="prefix")
    ) == ["run1"]
    # 同一前缀但项目不同 → 空
    assert list_runs(seeded, project="drug-screen", commit_sha="a1b2", commit_sha_mode="prefix") == []
    # 状态组合：run3 仍在进行
    assert names(list_runs(seeded, status="running", commit_sha="9abc", commit_sha_mode="prefix")) == ["run3"]
    assert list_runs(seeded, status="completed", commit_sha="9abc", commit_sha_mode="prefix") == []


def test_no_hit_returns_empty_list(seeded):
    assert list_runs(seeded, commit_sha="0000000", commit_sha_mode="prefix") == []
    assert list_runs(seeded, commit_sha="0" * 40, commit_sha_mode="exact") == []


def test_invalid_mode_rejected(seeded):
    with pytest.raises(DomainError):
        list_runs(seeded, commit_sha="a1b2", commit_sha_mode="fuzzy")


def test_blank_sha_ignored(seeded):
    assert names(list_runs(seeded, commit_sha="   ", commit_sha_mode="prefix")) == ["run1", "run2", "run3"]
